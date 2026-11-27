import base64
import csv
import hashlib
import io
from datetime import datetime
from math import isfinite

from markupsafe import Markup
from pytz import UTC, timezone

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.float_utils import float_compare


# A02. IMPORT DỮ LIỆU BÁN HÀNG TỪ POS
class GS25PosSaleImport(models.Model):
    _name = "gs25.pos.sale.import"
    _inherit = ["mail.thread", "gs25.replenishment.mixin"]
    _mail_post_access = "write"
    _description = "Phiếu import dữ liệu bán hàng POS GS25"
    _order = "import_date desc, id desc"

    _unique_name = models.Constraint(
        "UNIQUE(name)",
        "Mã phiếu import không được trùng.",
    )

    # Tên cột chấp nhận trong file CSV (tiếng Anh hoặc tiếng Việt không dấu)
    _gs25_column_aliases = {
        "receipt_ref": "receipt_ref",
        "ma_hoa_don": "receipt_ref",
        "line_no": "line_no",
        "dong": "line_no",
        "sale_datetime": "sale_datetime",
        "thoi_gian_ban": "sale_datetime",
        "product_code": "product_code",
        "ma_san_pham": "product_code",
        "quantity": "quantity",
        "so_luong": "quantity",
    }
    _gs25_required_columns = (
        "receipt_ref",
        "sale_datetime",
        "product_code",
        "quantity",
    )
    _gs25_datetime_formats = (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
        "%d/%m/%Y",
    )
    _gs25_max_rows = 20000

    # 1. THÔNG TIN PHIẾU IMPORT
    name = fields.Char(
        string="Mã phiếu",
        default="Phiếu mới",
        required=True,
        readonly=True,
        copy=False,
    )

    import_date = fields.Datetime(
        string="Thời điểm import",
        default=fields.Datetime.now,
        required=True,
        readonly=True,
    )

    company_id = fields.Many2one(
        "res.company",
        string="Công ty",
        default=lambda self: self.env.company,
        required=True,
        readonly=True,
    )

    warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Kho cửa hàng",
        default=lambda self: self.env.company._gs25_get_store_warehouse(),
        required=True,
        check_company=True,
    )

    file_data = fields.Binary(
        string="File dữ liệu bán hàng (CSV)",
        attachment=True,
        copy=False,
    )

    file_name = fields.Char(
        string="Tên file",
        copy=False,
    )

    file_checksum = fields.Char(
        string="Mã kiểm tra file",
        readonly=True,
        copy=False,
        index=True,
    )

    state = fields.Selection(
        [
            ("draft", "Nháp"),
            ("checked", "Đã kiểm tra dữ liệu"),
            ("done", "Đã cập nhật tồn kho"),
            ("cancelled", "Đã hủy"),
        ],
        string="Trạng thái",
        default="draft",
        required=True,
        readonly=True,
        copy=False,
    )

    line_ids = fields.One2many(
        "gs25.pos.sale.line",
        "import_id",
        string="Dòng bán hàng",
        readonly=True,
        copy=False,
    )

    note = fields.Text(
        string="Ghi chú",
        copy=False,
    )

    # 2. KẾT QUẢ CẬP NHẬT TỒN KHO
    picking_id = fields.Many2one(
        "stock.picking",
        string="Phiếu xuất bán",
        readonly=True,
        copy=False,
    )

    processed_by_id = fields.Many2one(
        "res.users",
        string="Người cập nhật tồn kho",
        readonly=True,
        copy=False,
    )

    processed_date = fields.Datetime(
        string="Thời điểm cập nhật tồn kho",
        readonly=True,
        copy=False,
    )

    # 3. THỐNG KÊ DÒNG DỮ LIỆU
    line_count = fields.Integer(
        string="Tổng số dòng",
        compute="_compute_line_stats",
    )

    valid_count = fields.Integer(
        string="Dòng hợp lệ",
        compute="_compute_line_stats",
    )

    error_count = fields.Integer(
        string="Dòng lỗi",
        compute="_compute_line_stats",
    )

    duplicate_count = fields.Integer(
        string="Dòng trùng",
        compute="_compute_line_stats",
    )

    done_count = fields.Integer(
        string="Dòng đã ghi nhận",
        compute="_compute_line_stats",
    )

    total_quantity = fields.Float(
        string="Tổng số lượng hợp lệ",
        compute="_compute_line_stats",
        digits="Product Unit",
    )

    @api.depends("line_ids.state", "line_ids.quantity")
    def _compute_line_stats(self):
        for record in self:
            lines = record.line_ids
            usable = lines.filtered(lambda line: line.state in ("valid", "done"))
            record.line_count = len(lines)
            record.valid_count = len(lines.filtered(lambda l: l.state == "valid"))
            record.error_count = len(lines.filtered(lambda l: l.state == "error"))
            record.duplicate_count = len(
                lines.filtered(lambda l: l.state == "duplicate")
            )
            record.done_count = len(lines.filtered(lambda l: l.state == "done"))
            record.total_quantity = sum(usable.mapped("quantity"))

    def _gs25_protected_fields(self):
        return {
            "name", "state", "file_checksum", "picking_id",
            "processed_by_id", "processed_date", "import_date",
            "line_ids", "company_id",
        }

    # 4. KIỂM SOÁT TẠO VÀ CHỈNH SỬA PHIẾU
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for key in self._gs25_protected_fields() - {"name", "company_id"}:
                vals.pop(key, None)

            vals["state"] = "draft"
            vals["name"] = self.env.ref(
                "gs25_replenishment.seq_gs25_pos_sale_import"
            ).sudo().next_by_id()

            if not vals["name"]:
                raise ValidationError("Không thể sinh mã phiếu import.")

        clean_context = {
            key: value
            for key, value in self.env.context.items()
            if not (
                key.startswith("default_")
                and key[8:] in self._gs25_protected_fields()
            )
        }
        return super(
            GS25PosSaleImport,
            self.with_context(clean_context),
        ).create(vals_list)

    def write(self, vals):
        self._gs25_lock_records()

        if self._gs25_protected_fields().intersection(vals):
            raise AccessError(
                "Không được chỉnh sửa trực tiếp thông tin xử lý của phiếu import. "
                "Vui lòng sử dụng các nút nghiệp vụ trên phiếu."
            )

        for record in self:
            if record.state in ("done", "cancelled"):
                raise AccessError(
                    "Phiếu import đã cập nhật tồn kho hoặc đã hủy, "
                    "không được chỉnh sửa."
                )

            if record.state == "checked" and {
                "file_data", "file_name", "warehouse_id",
            }.intersection(vals):
                raise AccessError(
                    "Phiếu đã kiểm tra dữ liệu. "
                    "Vui lòng đặt lại về Nháp trước khi thay file."
                )

        return super().write(vals)

    def unlink(self):
        self._gs25_lock_records("unlink")

        for record in self:
            if record.state not in ("draft", "cancelled") or record.picking_id:
                raise AccessError(
                    "Chỉ được xóa phiếu import ở trạng thái Nháp hoặc Đã hủy."
                )

        return super().unlink()

    # 5. ĐỌC VÀ KIỂM TRA FILE CSV
    def _gs25_decode_file(self):
        self.ensure_one()

        if not self.file_data:
            raise ValidationError(
                "Bạn chưa chọn file dữ liệu bán hàng.\n\n"
                "Vui lòng tải lên file CSV xuất từ máy POS."
            )

        raw = base64.b64decode(self.file_data)

        for encoding in ("utf-8-sig", "cp1258", "latin-1"):
            try:
                return raw, raw.decode(encoding)
            except UnicodeDecodeError:
                continue

        raise ValidationError("Không đọc được file. Vui lòng lưu file dạng CSV UTF-8.")

    @api.model
    def _gs25_normalize_header(self, header):
        key = (header or "").strip().lower().replace(" ", "_")
        return self._gs25_column_aliases.get(key, key)

    def _gs25_parse_datetime(self, value):
        value = (value or "").strip()

        if not value:
            return False

        user_tz = timezone(
            self.env.context.get("tz")
            or self.env.user.tz
            or "Asia/Ho_Chi_Minh"
        )

        for date_format in self._gs25_datetime_formats:
            try:
                local_dt = datetime.strptime(value, date_format)
            except ValueError:
                continue

            return user_tz.localize(local_dt).astimezone(UTC).replace(tzinfo=None)

        return False

    @api.model
    def _gs25_parse_quantity(self, value):
        value = (value or "").strip().replace(" ", "")

        if "," in value and "." not in value:
            value = value.replace(",", ".")

        try:
            quantity = float(value)
        except ValueError:
            return False

        return quantity if isfinite(quantity) else False

    def _gs25_find_products(self, codes):
        """Tìm sản phẩm theo mã vạch hoặc mã nội bộ."""
        products = self.env["product.product"].search([
            "|",
            ("barcode", "in", list(codes)),
            ("default_code", "in", list(codes)),
            ("company_id", "in", [False, self.company_id.id]),
        ])

        result = {}

        for product in products:
            for code in (product.barcode, product.default_code):
                if code and code in codes and code not in result:
                    result[code] = product

        return result

    @api.model
    def _gs25_make_sale_key(self, receipt_ref, line_no, product_code):
        """
        Khóa nhận diện một dòng bán hàng.
        Dùng số dòng nếu POS có xuất, nếu không dùng mã sản phẩm.
        """
        return "%s|%s" % (
            receipt_ref.strip().upper(),
            (line_no or product_code).strip().upper(),
        )

    def _gs25_build_line_vals(self, text):
        self.ensure_one()

        reader = csv.reader(io.StringIO(text), delimiter=self._gs25_sniff_delimiter(text))
        rows = list(reader)

        if not rows:
            raise ValidationError("File dữ liệu bán hàng không có nội dung.")

        headers = [self._gs25_normalize_header(header) for header in rows[0]]
        missing = [
            column for column in self._gs25_required_columns
            if column not in headers
        ]

        if missing:
            raise ValidationError(
                "File thiếu cột bắt buộc: %s.\n\n"
                "Các cột cần có: receipt_ref, sale_datetime, "
                "product_code, quantity (line_no không bắt buộc)."
                % ", ".join(missing)
            )

        data_rows = [
            row for row in rows[1:]
            if any((cell or "").strip() for cell in row)
        ]

        if not data_rows:
            raise ValidationError("File không có dòng dữ liệu bán hàng.")

        if len(data_rows) > self._gs25_max_rows:
            raise ValidationError(
                "File vượt quá %s dòng. Vui lòng tách file theo ngày bán."
                % self._gs25_max_rows
            )

        records = []

        for row_number, row in enumerate(data_rows, start=2):
            values = {
                header: (row[index].strip() if index < len(row) else "")
                for index, header in enumerate(headers)
            }
            values["row_number"] = row_number
            records.append(values)

        codes = {values["product_code"] for values in records if values["product_code"]}
        products = self._gs25_find_products(codes)

        now = fields.Datetime.now()
        seen_keys = set()
        vals_list = []

        for values in records:
            receipt_ref = values.get("receipt_ref", "")
            product_code = values.get("product_code", "")
            line_no = values.get("line_no", "")
            product = products.get(product_code)
            quantity = self._gs25_parse_quantity(values.get("quantity"))
            sale_datetime = self._gs25_parse_datetime(values.get("sale_datetime"))

            line_vals = {
                "row_number": values["row_number"],
                "receipt_ref": receipt_ref,
                "line_no": line_no,
                "product_code": product_code,
                "product_id": product.id if product else False,
                "quantity": quantity or 0.0,
                "sale_datetime": sale_datetime,
                "state": "valid",
                "message": False,
                "sale_key": False,
            }

            error = False

            if not receipt_ref:
                error = "Thiếu mã hóa đơn."
            elif not product_code:
                error = "Thiếu mã sản phẩm."
            elif not product:
                error = "Không tìm thấy sản phẩm có mã vạch/mã nội bộ %s." % product_code
            elif not product.is_storable:
                error = "Sản phẩm %s không được quản lý tồn kho." % product.display_name
            elif quantity is False:
                error = "Số lượng không hợp lệ."
            elif quantity <= 0:
                error = "Số lượng phải lớn hơn 0 (chưa hỗ trợ dòng trả hàng)."
            elif not sale_datetime:
                error = "Thời gian bán không hợp lệ."
            elif sale_datetime > now:
                error = "Thời gian bán ở tương lai."
            elif float_compare(
                quantity,
                product.uom_id.round(quantity),
                precision_rounding=product.uom_id.rounding,
            ) != 0:
                error = "Số lượng không phù hợp đơn vị tính của sản phẩm."

            if error:
                line_vals.update(state="error", message=error)
                vals_list.append(line_vals)
                continue

            sale_key = self._gs25_make_sale_key(receipt_ref, line_no, product_code)
            line_vals["sale_key"] = sale_key

            # A03. Tránh ghi nhận trùng dòng bán hàng trong cùng file
            if sale_key in seen_keys:
                line_vals.update(
                    state="duplicate",
                    message="Trùng dòng bán hàng trong cùng file.",
                )
            seen_keys.add(sale_key)
            vals_list.append(line_vals)

        return vals_list

    @api.model
    def _gs25_sniff_delimiter(self, text):
        first_line = text.splitlines()[0] if text else ""
        return ";" if first_line.count(";") > first_line.count(",") else ","

    def _gs25_mark_processed_duplicates(self):
        """A03. Đánh dấu các dòng đã được ghi nhận tồn kho ở phiếu khác."""
        self.ensure_one()

        lines = self.line_ids.filtered(lambda line: line.state == "valid")

        if not lines:
            return self.env["gs25.pos.sale.line"]

        processed = self.env["gs25.pos.sale.line"].search([
            ("is_processed", "=", True),
            ("company_id", "=", self.company_id.id),
            ("sale_key", "in", lines.mapped("sale_key")),
        ])
        processed_by_key = {line.sale_key: line for line in processed}
        duplicates = lines.filtered(lambda line: line.sale_key in processed_by_key)

        for line in duplicates:
            line._gs25_write_internal({
                "state": "duplicate",
                "message": "Đã ghi nhận tồn kho ở phiếu %s."
                % processed_by_key[line.sale_key].import_id.name,
            })

        return duplicates

    # 6. KIỂM TRA DỮ LIỆU (NHÁP -> ĐÃ KIỂM TRA)
    def action_check_data(self):
        self._gs25_lock_records()

        for record in self:
            if record.state not in ("draft", "checked"):
                raise ValidationError(
                    "Chỉ kiểm tra dữ liệu khi phiếu ở trạng thái Nháp."
                )

            record.company_id._gs25_check_replenishment_config()
            raw, text = record._gs25_decode_file()
            checksum = hashlib.sha256(raw).hexdigest()

            # A03. Không import lại cùng một file đã import
            same_file = self.search([
                ("id", "!=", record.id),
                ("file_checksum", "=", checksum),
                ("state", "!=", "cancelled"),
                ("company_id", "=", record.company_id.id),
            ], limit=1)

            if same_file:
                raise ValidationError(
                    "File này đã được import ở phiếu %s.\n\n"
                    "Không import lại cùng một file để tránh "
                    "ghi nhận trùng dữ liệu bán hàng." % same_file.name
                )

            line_vals = record._gs25_build_line_vals(text)

            record.line_ids.sudo().unlink()
            super(GS25PosSaleImport, record).write({
                "file_checksum": checksum,
                "state": "checked",
                "line_ids": [Command.create(vals) for vals in line_vals],
            })
            record._gs25_mark_processed_duplicates()

            record.message_post(body=Markup(
                "<p><strong>Đã kiểm tra dữ liệu bán hàng</strong></p>"
                "<p>Tổng số dòng: %s<br/>Hợp lệ: %s<br/>Lỗi: %s<br/>Trùng: %s</p>"
            ) % (
                record.line_count, record.valid_count,
                record.error_count, record.duplicate_count,
            ))

        return True

    def action_reset_draft(self):
        self._gs25_lock_records()

        for record in self:
            if record.state != "checked":
                raise ValidationError(
                    "Chỉ đặt lại phiếu đã kiểm tra nhưng chưa cập nhật tồn kho."
                )

            record.line_ids.sudo().unlink()
            super(GS25PosSaleImport, record).write({
                "state": "draft",
                "file_checksum": False,
            })

        return True

    def action_cancel(self):
        self._gs25_lock_records()

        for record in self:
            if record.state not in ("draft", "checked"):
                raise ValidationError(
                    "Không thể hủy phiếu đã cập nhật tồn kho."
                )

            super(GS25PosSaleImport, record).write({"state": "cancelled"})

        return True

    # 7. A03. XỬ LÝ DỮ LIỆU BÁN HÀNG VÀ CẬP NHẬT TỒN KHO
    def action_process_stock(self):
        self._gs25_lock_records()

        for record in self:
            record._gs25_process_stock()

        return True

    def _gs25_process_stock(self):
        self.ensure_one()

        if self.state != "checked" or self.picking_id:
            raise ValidationError(
                "Chỉ cập nhật tồn kho cho phiếu đã kiểm tra dữ liệu."
            )

        self.company_id._gs25_check_replenishment_config()
        warehouse = self.warehouse_id

        if not warehouse.lot_stock_id or not warehouse.out_type_id:
            raise ValidationError(
                "Kho %s chưa có vị trí tồn kho hoặc loại hoạt động xuất kho."
                % warehouse.display_name
            )

        # Khóa dữ liệu bán hàng đã ghi nhận để tránh hai phiếu xử lý cùng lúc
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (int(hashlib.sha1(b"gs25_pos_sale_import").hexdigest()[:8], 16),),
        )

        self._gs25_mark_processed_duplicates()
        lines = self.line_ids.filtered(lambda line: line.state == "valid")

        if not lines:
            raise ValidationError(
                "Không có dòng bán hàng hợp lệ để cập nhật tồn kho.\n\n"
                "Các dòng lỗi hoặc trùng sẽ không được ghi nhận."
            )

        quantity_by_product = {}

        for line in lines:
            quantity_by_product[line.product_id] = (
                quantity_by_product.get(line.product_id, 0.0) + line.quantity
            )

        picking = self._gs25_create_sale_picking(warehouse, quantity_by_product)
        now = fields.Datetime.now()

        for line in lines:
            line._gs25_write_internal({
                "state": "done",
                "is_processed": True,
                "message": False,
            })

        super(GS25PosSaleImport, self).write({
            "state": "done",
            "picking_id": picking.id,
            "processed_by_id": self.env.uid,
            "processed_date": now,
        })

        self.message_post(body=Markup(
            "<p><strong>Đã cập nhật tồn kho từ dữ liệu bán hàng</strong></p>"
            "<p>Phiếu xuất bán: %s<br/>Số dòng ghi nhận: %s<br/>"
            "Số dòng bỏ qua (lỗi/trùng): %s</p>"
        ) % (
            picking.name, len(lines),
            self.error_count + self.duplicate_count,
        ))
        return picking

    def _gs25_create_sale_picking(self, warehouse, quantity_by_product):
        """
        Tạo và xác thực phiếu xuất bán từ NVT/Tồn kho đến khách hàng.
        Sử dụng nghiệp vụ kho chuẩn, không cập nhật trực tiếp stock.quant.
        """
        location = warehouse.lot_stock_id
        customer_location = self.company_id._gs25_get_customer_location()
        picking_type = warehouse.out_type_id

        picking = self.env["stock.picking"].create({
            "picking_type_id": picking_type.id,
            "location_id": location.id,
            "location_dest_id": customer_location.id,
            "origin": self.name,
            "company_id": self.company_id.id,
            "move_ids": [
                Command.create({
                    "product_id": product.id,
                    "product_uom_qty": quantity,
                    "product_uom": product.uom_id.id,
                    "location_id": location.id,
                    "location_dest_id": customer_location.id,
                    "company_id": self.company_id.id,
                })
                for product, quantity in quantity_by_product.items()
            ],
        })

        picking.action_confirm()
        picking.action_assign()

        shortages = []

        for move in picking.move_ids:
            if float_compare(
                move.quantity,
                move.product_uom_qty,
                precision_rounding=move.product_uom.rounding,
            ) < 0:
                shortages.append(
                    "- %s: cần %s, tồn khả dụng %s %s" % (
                        move.product_id.display_name,
                        move.product_uom_qty,
                        move.quantity,
                        move.product_uom.name,
                    )
                )

        if shortages:
            raise ValidationError(
                "Tồn kho tại %s không đủ để ghi nhận dữ liệu bán hàng:\n%s\n\n"
                "Vui lòng kiểm tra lại tồn kho thực tế hoặc dữ liệu POS "
                "trước khi cập nhật." % (location.complete_name, "\n".join(shortages))
            )

        picking.move_ids.picked = True
        picking.with_context(
            skip_backorder=True,
            skip_expired=True,
            skip_sms=True,
        ).button_validate()

        if picking.state != "done":
            raise ValidationError(
                "Phiếu xuất bán %s chưa hoàn tất. "
                "Vui lòng kiểm tra cấu hình Inventory." % picking.name
            )

        return picking

    def action_view_picking(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Phiếu xuất bán",
            "res_model": "stock.picking",
            "res_id": self.picking_id.id,
            "view_mode": "form",
        }

    # 8. A06. SẢN LƯỢNG BÁN TRUNG BÌNH MỖI NGÀY
    @api.model
    def _gs25_get_average_daily_sales(self, products, days, company=None):
        """Trả về {product_id: số lượng bán trung bình/ngày} trong `days` ngày gần nhất."""
        company = company or self.env.company

        if not products or days <= 0:
            return {}

        date_from = fields.Datetime.subtract(fields.Datetime.now(), days=days)
        groups = self.env["gs25.pos.sale.line"]._read_group(
            [
                ("is_processed", "=", True),
                ("company_id", "=", company.id),
                ("product_id", "in", products.ids),
                ("sale_datetime", ">=", date_from),
            ],
            groupby=["product_id"],
            aggregates=["quantity:sum"],
        )

        return {
            product.id: quantity / days
            for product, quantity in groups
        }


# DÒNG DỮ LIỆU BÁN HÀNG POS
class GS25PosSaleLine(models.Model):
    _name = "gs25.pos.sale.line"
    _description = "Dòng dữ liệu bán hàng POS GS25"
    _order = "import_id desc, row_number, id"

    # A03. Một dòng bán hàng chỉ được ghi nhận tồn kho một lần
    _unique_processed_sale_key = models.UniqueIndex(
        "(company_id, sale_key) WHERE is_processed IS TRUE",
        "Dòng bán hàng này đã được ghi nhận tồn kho trước đó.",
    )

    import_id = fields.Many2one(
        "gs25.pos.sale.import",
        string="Phiếu import",
        required=True,
        ondelete="cascade",
        index=True,
    )

    company_id = fields.Many2one(
        "res.company",
        related="import_id.company_id",
        store=True,
        index=True,
    )

    row_number = fields.Integer(string="Dòng trong file", readonly=True)
    receipt_ref = fields.Char(string="Mã hóa đơn", readonly=True)
    line_no = fields.Char(string="Số dòng hóa đơn", readonly=True)
    sale_datetime = fields.Datetime(string="Thời gian bán", readonly=True)
    product_code = fields.Char(string="Mã sản phẩm", readonly=True)

    product_id = fields.Many2one(
        "product.product",
        string="Sản phẩm",
        readonly=True,
        index=True,
    )

    uom_id = fields.Many2one(
        "uom.uom",
        related="product_id.uom_id",
        string="Đơn vị",
    )

    quantity = fields.Float(
        string="Số lượng bán",
        digits="Product Unit",
        readonly=True,
    )

    sale_key = fields.Char(
        string="Khóa dòng bán hàng",
        readonly=True,
        index=True,
    )

    is_processed = fields.Boolean(
        string="Đã ghi nhận tồn kho",
        readonly=True,
        default=False,
        index=True,
    )

    state = fields.Selection(
        [
            ("valid", "Hợp lệ"),
            ("error", "Lỗi"),
            ("duplicate", "Trùng"),
            ("done", "Đã ghi nhận"),
        ],
        string="Kết quả",
        default="valid",
        readonly=True,
    )

    message = fields.Char(string="Thông báo", readonly=True)

    def write(self, vals):
        if not self.env.context.get("gs25_pos_line_internal"):
            raise AccessError(
                "Không được chỉnh sửa trực tiếp dòng dữ liệu bán hàng. "
                "Vui lòng import lại file từ POS."
            )
        return super().write(vals)

    def _gs25_write_internal(self, vals):
        return self.with_context(gs25_pos_line_internal=True).write(vals)

    def unlink(self):
        if any(line.is_processed for line in self):
            raise AccessError(
                "Không được xóa dòng bán hàng đã ghi nhận tồn kho."
            )
        return super().unlink()

from datetime import timedelta
from odoo import api, fields, models
from odoo.osv import expression
from odoo.exceptions import AccessError

class GS25StockLot(models.Model):
    _inherit = "stock.lot"

  
    # 1. TRẠNG THÁI HẠN SỬ DỤNG
    gs25_expiry_status = fields.Selection(
        selection=[
            ("no_date", "Chưa có hạn sử dụng"),
            ("normal", "Còn hạn"),
            ("near_expiry", "Cận hạn"),
            ("expired", "Hết hạn"),
        ],
        string="Trạng thái hạn sử dụng GS25",
        compute="_compute_gs25_expiry_status",
        search="_search_gs25_expiry_status",
    )


    # 2. TỒN KHO TẠI CHI NHÁNH NGUYỄN VĂN TRỖI
    gs25_nvt_quantity = fields.Float(
        string="Tồn kho Nguyễn Văn Trỗi",
        compute="_compute_gs25_nvt_quantity",
        search="_search_gs25_nvt_quantity",
    )

    def _get_gs25_nvt_location(self):
        """Tìm vị trí tồn kho của chi nhánh NVT."""
        return self.env["stock.location"].search(
            [
                ("complete_name", "=", "NVT/Tồn kho"),
                ("usage", "=", "internal"),
                ("company_id", "in", [
                    False,
                    self.env.company.id,
                ]),
            ],
            limit=1,
        )

    def _get_gs25_nvt_quants(self):
        """
        Lấy các quant của lô hàng tại kho NVT
        và các vị trí kho con.
        """

        self.ensure_one()

        location = self._get_gs25_nvt_location()

        if not location:
            return self.env["stock.quant"]

        return self.env["stock.quant"].search([
            ("lot_id", "=", self.id),
            ("product_id", "=", self.product_id.id),
            ("location_id", "child_of", location.id),
            ("location_id.usage", "=", "internal"),
            ("company_id", "=", self.env.company.id),
        ])

    def _compute_gs25_nvt_quantity(self):
        """Tính tổng tồn kho của từng lô tại NVT."""

        for lot in self:
            lot.gs25_nvt_quantity = 0.0

        if not self:
            return

        location = self._get_gs25_nvt_location()

        if not location:
            return

        quants = self.env["stock.quant"].search([
            ("lot_id", "in", self.ids),
            ("location_id", "child_of", location.id),
            ("location_id.usage", "=", "internal"),
            ("company_id", "=", self.env.company.id),
        ])

        quantity_by_lot = {}

        for quant in quants:
            lot_id = quant.lot_id.id

            quantity_by_lot[lot_id] = (
                quantity_by_lot.get(lot_id, 0.0)
                + quant.quantity
            )

        for lot in self:
            lot.gs25_nvt_quantity = quantity_by_lot.get(
                lot.id,
                0.0,
            )

   
    # 3. TÌM KIẾM LÔ CÒN TỒN KHO TẠI NVT
    def _search_gs25_nvt_quantity(self, operator, value):
        """
        Hỗ trợ domain:
        ('gs25_nvt_quantity', '>', 0)
        """

        if operator != ">" or value != 0:
            raise NotImplementedError(
                "Chỉ hỗ trợ lọc tồn kho NVT lớn hơn 0."
            )

        location = self._get_gs25_nvt_location()

        if not location:
            return [("id", "=", 0)]

        quants = self.env["stock.quant"].search([
            ("location_id", "child_of", location.id),
            ("location_id.usage", "=", "internal"),
            ("lot_id", "!=", False),
            ("company_id", "=", self.env.company.id),
        ])

        quantity_by_lot = {}

        for quant in quants:
            lot_id = quant.lot_id.id

            quantity_by_lot[lot_id] = (
                quantity_by_lot.get(lot_id, 0.0)
                + quant.quantity
            )

        lot_ids = [
            lot_id
            for lot_id, quantity in quantity_by_lot.items()
            if quantity > 0
        ]

        return [("id", "in", lot_ids)]


    # 4. TÍNH TRẠNG THÁI HẠN SỬ DỤNG
    @api.depends("expiration_date")
    def _compute_gs25_expiry_status(self):
        today = fields.Date.context_today(self)
        now = fields.Datetime.now()
        warning_days = 2

        for lot in self:

            if not lot.expiration_date:
                lot.gs25_expiry_status = "no_date"
                continue

            expiry_date = fields.Datetime.context_timestamp(
                lot,
                lot.expiration_date,
            ).date()

            # Kiểm tra hạn sử dụng theo thời điểm thực tế
            if lot.expiration_date <= now:
                lot.gs25_expiry_status = "expired"

            elif expiry_date <= today + timedelta(
                days=warning_days
            ):
                lot.gs25_expiry_status = "near_expiry"

            else:
                lot.gs25_expiry_status = "normal"


    # 5. TÌM KIẾM THEO TRẠNG THÁI HẠN SỬ DỤNG
    def _search_gs25_expiry_status(self, operator, value):

        from datetime import datetime, time
        from pytz import timezone, UTC

        if operator == "=":
            value = [value]

        elif operator != "in":
            return NotImplemented

        if not isinstance(value, (list, tuple)):
            return NotImplemented

        today = fields.Date.context_today(self)
        now = fields.Datetime.now()

        # Kết thúc ngày cảnh báo theo múi giờ người dùng
        warning_end_date = today + timedelta(days=3)

        user_tz = timezone(
            self.env.context.get("tz")
            or self.env.user.tz
            or "UTC"
        )

        warning_end = user_tz.localize(
            datetime.combine(
                warning_end_date,
                time.min,
            )
        ).astimezone(UTC).replace(tzinfo=None)

        domains = []

        if "no_date" in value:
            domains.append([
                ("expiration_date", "=", False),
            ])

        if "expired" in value:
            domains.append([
                ("expiration_date", "!=", False),
                ("expiration_date", "<=", now),
            ])

        if "near_expiry" in value:
            domains.append([
                ("expiration_date", ">", now),
                ("expiration_date", "<", warning_end),
            ])

        if "normal" in value:
            domains.append([
                (
                    "expiration_date",
                    ">=",
                    warning_end,
                ),
            ])

        if not domains:
            return [("id", "=", 0)]

        return expression.OR(domains)


    # 6. TRẠNG THÁI XỬ LÝ HÀNG HÓA
    gs25_handling_status = fields.Selection(
        selection=[
            ("none", "Chưa xử lý"),
            ("priority_sale", "Ưu tiên bán"),
            ("monitor", "Đang theo dõi"),
            ("removed", "Đã thực hiện loại bỏ"),
        ],
        string="Phương án xử lý gần nhất",
        default="none",
        readonly=True,
        copy=False,
    )


    # 7. THÔNG TIN ƯU TIÊN BÁN
    gs25_priority_quantity = fields.Float(
        string="Số lượng ưu tiên bán",
        default=0,
        readonly=True,
        copy=False,
    )

   
    # 8. THÔNG TIN THEO DÕI VÀ KIỂM TRA LẠI
    gs25_monitor_quantity = fields.Float(
        string="Số lượng cần theo dõi",
        default=0,
        readonly=True,
        copy=False,
    )

    gs25_next_check_date = fields.Datetime(
        string="Thời điểm kiểm tra lại",
        readonly=True,
        copy=False,
    )

    gs25_reminder_sent = fields.Boolean(
        string="Đã gửi nhắc lịch kiểm tra lại",
        default=False,
        readonly=True,
        copy=False,
    )

    gs25_monitor_overdue = fields.Boolean(
        string="Quá hạn kiểm tra lại",
        compute="_compute_gs25_monitor_overdue",
        search="_search_gs25_monitor_overdue",
    )

    @api.depends(
        "gs25_handling_status",
        "gs25_next_check_date",
    )
    def _compute_gs25_monitor_overdue(self):

        now = fields.Datetime.now()

        for lot in self:
            lot.gs25_monitor_overdue = bool(
                lot.gs25_handling_status == "monitor"
                and lot.gs25_next_check_date
                and lot.gs25_next_check_date <= now
            )

    def _search_gs25_monitor_overdue(
        self,
        operator,
        value,
    ):

        if operator not in ("=", "!="):
            return NotImplemented

        if not isinstance(value, bool):
            return NotImplemented

        overdue_domain = [
            ("gs25_handling_status", "=", "monitor"),
            ("gs25_next_check_date", "!=", False),
            (
                "gs25_next_check_date",
                "<=",
                fields.Datetime.now(),
            ),
        ]

        is_overdue = (
            value if operator == "=" else not value
        )

        if is_overdue:
            return overdue_domain

        return [
            "!",
            "&",
            "&",
            overdue_domain[0],
            overdue_domain[1],
            overdue_domain[2],
        ]


    # 9. THÔNG TIN XỬ LÝ GẦN NHẤT
    gs25_last_handling_date = fields.Datetime(
        string="Thời điểm xử lý gần nhất",
        readonly=True,
        copy=False,
    )

    gs25_last_handling_user_id = fields.Many2one(
        "res.users",
        string="Người xử lý gần nhất",
        readonly=True,
        copy=False,
    )

   
    # 10. LỊCH SỬ PHIẾU KIỂM TRA
    gs25_date_check_record_ids = fields.One2many(
        "gs25.date.check.record",
        "lot_id",
        string="Lịch sử phiếu kiểm tra",
        readonly=True,
        copy=False,
    )

    # 11. KIỂM SOÁT QUYỀN CẬP NHẬT THÔNG TIN XỬ LÝ
    def _get_gs25_handling_fields(self):

        return {
            "gs25_handling_status",
            "gs25_priority_quantity",
            "gs25_monitor_quantity",
            "gs25_next_check_date",
            "gs25_last_handling_date",
            "gs25_last_handling_user_id",
            "gs25_reminder_sent",
        }

    @api.model_create_multi
    def create(self, vals_list):

        protected_fields = (
            self._get_gs25_handling_fields()
            | {"gs25_date_check_record_ids"}
        )

        for vals in vals_list:
            if protected_fields.intersection(vals):
                raise AccessError(
                    "Không được thiết lập trực tiếp "
                    "thông tin xử lý Date Check khi tạo lô hàng."
                )

        # Ngăn thiết lập giá trị xử lý qua context mặc định
        clean_context = dict(self.env.context)

        for field_name in protected_fields:
            clean_context.pop(
                f"default_{field_name}",
                None,
            )

        return super(
            GS25StockLot,
            self.with_context(clean_context),
        ).create(vals_list)

    def write(self, vals):

        protected_fields = (
            self._get_gs25_handling_fields()
            | {"gs25_date_check_record_ids"}
        )

        if protected_fields.intersection(vals):
            raise AccessError(
                "Không được chỉnh sửa trực tiếp "
                "thông tin xử lý Date Check. "
                "Vui lòng thực hiện thông qua phiếu kiểm tra."
            )

        return super().write(vals)

    def _gs25_update_handling(self, vals):

        self.ensure_one()

        if not self.env.user.has_group(
            "gs25_date_check.group_gs25_date_check_manager"
        ):
            raise AccessError(
                "Chỉ quản lý Date Check "
                "mới được cập nhật kết quả xử lý."
            )

        self.check_access("write")

        protected_fields = self._get_gs25_handling_fields()

        if not set(vals).issubset(protected_fields):
            raise AccessError(
                "Thông tin cập nhật xử lý không hợp lệ."
            )

        vals = dict(vals)
        vals["gs25_reminder_sent"] = False

        return super().write(vals)

    def _gs25_cron_monitor_reminder(self):
        lots = self.search([
            ("gs25_handling_status", "=", "monitor"),
            ("gs25_next_check_date", "!=", False),
            ("gs25_next_check_date", "<=", fields.Datetime.now()),
            ("gs25_reminder_sent", "=", False),
            ("gs25_nvt_quantity", ">", 0),
        ], order="id")

        for lot in lots:
            lot.flush_recordset()
            self.env.cr.execute(
                "SELECT id FROM stock_lot WHERE id = %s FOR UPDATE SKIP LOCKED",
                (lot.id,),
            )
            if not self.env.cr.fetchone():
                continue

            lot.invalidate_recordset()
            if (
                lot.gs25_handling_status != "monitor"
                or lot.gs25_reminder_sent
                or not lot.gs25_next_check_date
                or lot.gs25_next_check_date > fields.Datetime.now()
            ):
                continue

            quants = lot._get_gs25_nvt_quants()
            quants.invalidate_recordset()
            if sum(quants.mapped("quantity")) <= 0:
                continue

            record = self.env["gs25.date.check.record"].search([
                ("lot_id", "=", lot.id),
                ("state", "=", "done"),
                ("proposed_action", "=", "monitor"),
                ("next_check_date", "=", lot.gs25_next_check_date),
                ("processed_date", "=", lot.gs25_last_handling_date),
            ], order="id desc", limit=1)

            if record and record._gs25_notify_monitor_reminder():
                super(GS25StockLot, lot).write({
                    "gs25_reminder_sent": True,
                })

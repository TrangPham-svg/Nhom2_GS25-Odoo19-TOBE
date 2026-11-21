from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.float_utils import float_compare
from math import isfinite, isclose
from markupsafe import Markup
from odoo.tools import format_datetime


class GS25DateCheckRecord(models.Model):
    _name = "gs25.date.check.record"
    _inherit = ["mail.thread"]
    _mail_post_access = "write"
    _description = "Phiếu kiểm tra hạn sử dụng GS25"
    _order = "check_date desc, id desc"

    _unique_name = models.Constraint(
        "UNIQUE(name)",
        "Mã phiếu kiểm tra không được trùng.",
    )

    # 1. THÔNG TIN PHIẾU KIỂM TRA
    name = fields.Char(
        string="Mã phiếu",
        default="Phiếu mới",
        required=True,
        readonly=True,
        copy=False,
    )

    lot_id = fields.Many2one(
        "stock.lot",
        string="Số lô",
        required=True,
        ondelete="restrict",
    )

    product_id = fields.Many2one(
        "product.product",
        string="Sản phẩm",
        related="lot_id.product_id",
        readonly=True,
        store=True,
    )

    expiration_date = fields.Datetime(
        string="Ngày hết hạn",
        related="lot_id.expiration_date",
        readonly=True,
    )

    check_date = fields.Datetime(
        string="Ngày kiểm tra",
        default=fields.Datetime.now,
        required=True,
    )

    checker_id = fields.Many2one(
        "res.users",
        string="Người kiểm tra",
        default=lambda self: self.env.user,
        required=True,
    )

    checked_quantity = fields.Float(
        string="Số lượng kiểm tra",
        required=True,
        default=0,
    )

    # 2. KẾT QUẢ KIỂM TRA
    quality_result = fields.Selection(
        [
            ("good", "Đạt yêu cầu"),
            ("bad", "Không đạt yêu cầu"),
        ],
        string="Kết quả kiểm tra",
        required=False,
        default=False,
        copy=False,
    )

    proposed_action = fields.Selection(
        [
            ("priority_sale", "Ưu tiên bán"),
            ("monitor", "Tiếp tục theo dõi"),
            ("remove", "Đề xuất loại bỏ"),
        ],
        string="Đề xuất xử lý",
        required=False,
        default=False,
        copy=False,
    )

    state = fields.Selection(
        [
            ("draft", "Nháp"),
            ("waiting", "Chờ quản lý xác nhận"),
            ("approved", "Đã xác nhận"),
            ("done", "Đã xử lý"),
            ("cancelled", "Đã hủy"),
        ],
        string="Trạng thái",
        default="draft",
        required=True,
        copy=False,
    )

    note = fields.Text(
        string="Ghi chú",
        copy=False,
    )

    # 3. PHẢN HỒI CỦA QUẢN LÝ
    return_reason = fields.Text(
        string="Lý do yêu cầu bổ sung",
        copy=False,
    )

    returned_by_id = fields.Many2one(
        "res.users",
        string="Quản lý trả lại",
        readonly=True,
        copy=False,
    )

    returned_date = fields.Datetime(
        string="Thời điểm trả lại",
        readonly=True,
        copy=False,
    )

    # THÔNG TIN HỦY VÀ THỰC HIỆN
    cancel_reason = fields.Text(readonly=True, copy=False, string="Lý do hủy")
    cancelled_by_id = fields.Many2one("res.users", readonly=True, copy=False, string="Người hủy")
    cancelled_date = fields.Datetime(readonly=True, copy=False, string="Thời điểm hủy")
    processed_by_id = fields.Many2one("res.users", readonly=True, copy=False, string="Người xử lý")
    processed_date = fields.Datetime(readonly=True, copy=False, string="Thời điểm xử lý")
    processed_quantity = fields.Float(readonly=True, copy=False, string="Số lượng xử lý")
    processing_note = fields.Text(readonly=True, copy=False, string="Ghi chú xử lý")
    next_check_date = fields.Datetime(readonly=True, copy=False, string="Kiểm tra lại lúc")
    scrap_ids = fields.Many2many("stock.scrap", "gs25_date_check_scrap_rel", "record_id", "scrap_id", readonly=True, copy=False, string="Phiếu Scrap")

    def _gs25_protected_fields(self):
        return {"cancel_reason", "cancelled_by_id", "cancelled_date",
                "processed_by_id", "processed_date", "processed_quantity",
                "processing_note", "next_check_date", "scrap_ids", "create_uid"}

    can_edit_draft = fields.Boolean(compute="_compute_draft_permissions")
    can_delete_draft = fields.Boolean(compute="_compute_draft_permissions")

    @api.depends("state", "create_uid", "returned_date")
    @api.depends_context("uid")
    def _compute_draft_permissions(self):
        is_manager = self.env.user.has_group(
            "gs25_date_check.group_gs25_date_check_manager"
        )
        for record in self:
            is_owner = not record._origin.id or record.create_uid.id == self.env.uid
            record.can_edit_draft = record.state == "draft" and is_owner
            record.can_delete_draft = bool(
                record._origin.id and record.state == "draft"
                and (is_owner or is_manager)
                and not record.returned_date
            )

    # 4. KIỂM TRA DỮ LIỆU
    @api.constrains("checked_quantity")
    def _check_quantity(self):
        for record in self:
            if not isfinite(record.checked_quantity) or record.checked_quantity <= 0:
                raise ValidationError(
                    "Số lượng kiểm tra phải lớn hơn 0."
                )

    # 5. KIỂM SOÁT TẠO PHIẾU
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            for key in self._gs25_protected_fields():
                vals.pop(key, None)
                if key != "create_uid":
                    vals[key] = False
            if vals.get("state", "draft") != "draft":
                raise AccessError(
                    "Phiếu mới phải ở trạng thái Nháp."
                )

            vals["state"] = "draft"
            vals["name"] = self.env.ref(
                "gs25_date_check.seq_gs25_date_check_record"
            ).sudo().next_by_id()
            if not vals["name"]:
                raise ValidationError("Không thể sinh mã phiếu kiểm tra.")

            # Không cho tự tạo thông tin phản hồi quản lý
            vals["return_reason"] = False
            vals["returned_by_id"] = False
            vals["returned_date"] = False

        clean_context = dict(self.env.context)
        clean_context.pop("default_create_uid", None)
        return super(GS25DateCheckRecord, self.with_context(clean_context)).create(vals_list)

    # 6. KIỂM TRA TÍNH HỢP LỆ CỦA KẾT QUẢ
    def _check_inspection_result(self):
        for record in self:

            # Bắt buộc nhân viên đánh giá chất lượng
            if not record.quality_result:
                raise ValidationError(
                    "Bạn chưa chọn kết quả kiểm tra.\n\n"
                    "Vui lòng kiểm tra hàng hóa thực tế "
                    "và chọn 'Đạt yêu cầu' hoặc "
                    "'Không đạt yêu cầu'."
                )

            # Bắt buộc nhân viên chọn đề xuất xử lý
            if not record.proposed_action:
                raise ValidationError(
                    "Bạn chưa chọn đề xuất xử lý.\n\n"
                    "Vui lòng chọn một trong các phương án: "
                    "'Ưu tiên bán', 'Tiếp tục theo dõi' "
                    "hoặc 'Đề xuất loại bỏ'."
                )

            # Không ưu tiên bán hàng không đạt yêu cầu
            if (
                record.quality_result == "bad"
                and record.proposed_action == "priority_sale"
            ):
                raise ValidationError(
                    "Kết quả kiểm tra và đề xuất xử lý "
                    "không phù hợp.\n\n"
                    "Hàng hóa không đạt yêu cầu "
                    "không được đề xuất ưu tiên bán.\n\n"
                    "Vui lòng chọn phương án xử lý khác."
                )

            # Không ưu tiên bán hàng đã hết hạn
            if (
                record.expiration_date
                and record.expiration_date <= fields.Datetime.now()
                and record.proposed_action == "priority_sale"
            ):
                raise ValidationError(
                    "Không thể đề xuất ưu tiên bán "
                    "đối với hàng đã hết hạn sử dụng.\n\n"
                    "Vui lòng chọn phương án xử lý phù hợp."
                )

            # Bắt buộc ghi chú khi hàng không đạt
            # hoặc có đề xuất loại bỏ
            if (
                record.quality_result == "bad"
                or record.proposed_action == "remove"
            ):
                if not (record.note or "").strip():
                    raise ValidationError(
                        "Bạn chưa nhập ghi chú kiểm tra.\n\n"
                        "Vui lòng ghi rõ tình trạng hàng hóa "
                        "hoặc lý do đề xuất loại bỏ "
                        "để quản lý có căn cứ xác nhận."
                    )

    # 7. GỬI PHIẾU CHO QUẢN LÝ
    def action_submit(self):
        self._gs25_lock_records()
        for record in self:
            if record.state != "draft":
                raise ValidationError(
                    "Chỉ có thể gửi phiếu đang ở trạng thái Nháp."
                )

            if record.create_uid.id != self.env.uid:
                raise AccessError("Chỉ người tạo phiếu mới được gửi quản lý.")

            # Kiểm tra kết quả và đề xuất xử lý
            record._check_inspection_result()

            # Kiểm tra tồn kho thực tế của lô tại NVT
            nvt_location = (
                record.lot_id._get_gs25_nvt_location()
            )

            if not nvt_location:
                raise ValidationError(
                    "Không tìm thấy vị trí kho NVT/Tồn kho. "
                    "Vui lòng kiểm tra cấu hình kho."
                )

            available_quantity = (
                record.lot_id.gs25_nvt_quantity
            )

            rounding = (
                record.product_id.uom_id.rounding
                or 0.01
            )

            if float_compare(
                record.checked_quantity,
                available_quantity,
                precision_rounding=rounding,
            ) > 0:
                raise ValidationError(
                    "Số lượng kiểm tra vượt tồn kho tại "
                    "chi nhánh Nguyễn Văn Trỗi.\n\n"
                    "Số lô: %s\n"
                    "Tồn kho hệ thống: %s\n"
                    "Số lượng kiểm tra: %s\n\n"
                    "Vui lòng kiểm tra lại số lượng "
                    "trước khi gửi quản lý."
                    % (
                        record.lot_id.name,
                        available_quantity,
                        record.checked_quantity,
                    )
                )

        # Chuyển trạng thái bằng phương thức nội bộ
        self._gs25_update_state("waiting")
        return True

    # 8. QUẢN LÝ XÁC NHẬN PHIẾU
    def action_approve(self):
        self._gs25_lock_records()
        manager_group = (
            "gs25_date_check.group_gs25_date_check_manager"
        )

        if not self.env.user.has_group(manager_group):
            raise AccessError(
                "Chỉ quản lý GS25 Date Check "
                "mới được xác nhận phiếu."
            )

        for record in self:
            if record.state != "waiting":
                raise ValidationError(
                    "Chỉ có thể xác nhận phiếu "
                    "đang chờ quản lý."
                )

            # Kiểm tra lại kết quả trước khi xác nhận
            record._check_inspection_result()

        self._gs25_update_state("approved")
        return True

    # 9. QUẢN LÝ YÊU CẦU BỔ SUNG THÔNG TIN
    def action_return_to_draft(self):
        self._gs25_lock_records()
        manager_group = (
            "gs25_date_check.group_gs25_date_check_manager"
        )

        if not self.env.user.has_group(manager_group):
            raise AccessError(
                "Chỉ quản lý GS25 Date Check "
                "mới được yêu cầu bổ sung thông tin."
            )

        for record in self:

            # Chỉ trả lại phiếu đang chờ xác nhận
            if record.state != "waiting":
                raise ValidationError(
                    "Chỉ có thể trả lại phiếu "
                    "đang chờ quản lý xác nhận."
                )

            # Bắt buộc nhập lý do trả lại
            if not (record.return_reason or "").strip():
                raise ValidationError(
                    "Bạn chưa nhập lý do yêu cầu bổ sung.\n\n"
                    "Vui lòng ghi rõ nội dung cần bổ sung "
                    "để nhân viên có thể chỉnh sửa phiếu."
                )

            # Trả phiếu về Nháp và lưu thông tin quản lý
            super(GS25DateCheckRecord, record).write({
                "state": "draft",
                "returned_by_id": self.env.user.id,
                "returned_date": fields.Datetime.now(),
            })

        return True

    # 10. CHUYỂN TRẠNG THÁI NỘI BỘ
    def _gs25_update_state(self, new_state):
        """
        Chỉ sử dụng trong các phương thức
        chuyển trạng thái đã kiểm tra điều kiện.
        """
        if new_state not in ("waiting", "approved"):
            raise ValidationError(
                "Trạng thái chuyển đổi không hợp lệ."
            )

        return super(GS25DateCheckRecord, self).write({
            "state": new_state,
        })

    # 11. KHÓA CHỈNH SỬA PHIẾU
    def write(self, vals):
        self._gs25_lock_records()

        if "name" in vals:
            raise AccessError("Không được thay đổi mã phiếu kiểm tra.")

        if self._gs25_protected_fields().intersection(vals):
            raise AccessError("Không được sửa trực tiếp thông tin xử lý.")

        # Không cho đổi trạng thái bằng write thông thường
        if "state" in vals:
            raise AccessError(
                "Không được thay đổi trạng thái trực tiếp. "
                "Hãy sử dụng nút xử lý trên phiếu."
            )

        # Không cho sửa trực tiếp thông tin người trả lại
        # và thời điểm trả lại
        if {"returned_by_id", "returned_date"}.intersection(vals):
            raise AccessError(
                "Không được thay đổi trực tiếp "
                "thông tin phản hồi của quản lý."
            )

        manager_group = (
            "gs25_date_check.group_gs25_date_check_manager"
        )

        is_manager = self.env.user.has_group(manager_group)

        for record in self:

            if record.state == "draft" and record.create_uid.id != self.env.uid:
                raise AccessError("Chỉ người tạo phiếu mới được chỉnh sửa phiếu Nháp.")

            # Phiếu đã xác nhận không được chỉnh sửa
            if record.state in ("approved", "done", "cancelled"):
                raise AccessError(
                    "Phiếu đã xác nhận, xử lý hoặc hủy, "
                    "không được chỉnh sửa."
                )

            # Chỉ quản lý được nhập lý do trả lại
            # khi phiếu đang chờ xác nhận
            if "return_reason" in vals:
                if not is_manager or record.state != "waiting":
                    raise AccessError(
                        "Chỉ quản lý mới được nhập lý do "
                        "yêu cầu bổ sung đối với phiếu "
                        "đang chờ xác nhận."
                    )

            # Phiếu đang chờ chỉ cho quản lý
            # chỉnh sửa trường lý do trả lại
            if record.state == "waiting":
                if not (
                    is_manager
                    and set(vals).issubset({"return_reason"})
                ):
                    raise AccessError(
                        "Phiếu đã gửi quản lý, "
                        "không được chỉnh sửa nội dung."
                    )

        return super().write(vals)

    # 12. XÓA PHIẾU NHÁP
    def action_delete_draft(self):
        self.ensure_one()
        self.unlink()
        return self.env["ir.actions.actions"]._for_xml_id(
            "gs25_date_check.action_gs25_date_check_records"
        )

    def unlink(self):
        self._gs25_lock_records("unlink")
        is_manager = self.env.user.has_group(
            "gs25_date_check.group_gs25_date_check_manager"
        )
        for record in self:
            if record.state != "draft":
                raise AccessError("Chỉ được xóa phiếu ở trạng thái Nháp.")
            if record.create_uid.id != self.env.uid and not is_manager:
                raise AccessError("Bạn chỉ được xóa phiếu do chính mình tạo.")
            if record.returned_date:
                raise AccessError("Không được xóa phiếu đã được quản lý trả lại.")
        return super().unlink()

    # 13. KIỂM SOÁT QUẢN LÝ VÀ KHÓA PHIẾU KHI XỬ LÝ
    def _gs25_lock_for_manager(self):
        self.ensure_one()
        if not self.env.user.has_group("gs25_date_check.group_gs25_date_check_manager"):
            raise AccessError("Chỉ quản lý Date Check được thực hiện thao tác này.")
        self.check_access("write")
        self.flush_recordset()
        self.env.cr.execute("SELECT id FROM gs25_date_check_record WHERE id = %s FOR UPDATE", (self.id,))
        self.invalidate_recordset()
        self.check_access("write")

    def action_open_cancel_wizard(self):
        self._gs25_lock_for_manager()
        self._gs25_check_cancel_state()
        return {"type": "ir.actions.act_window", "name": "Hủy phiếu",
                "res_model": "gs25.date.check.cancel.wizard", "view_mode": "form",
                "target": "new", "context": {"default_record_id": self.id}}

    def _gs25_check_cancel_state(self):
        if not (self.state == "waiting" or (self.state == "draft" and self.returned_date)):
            raise ValidationError("Chỉ hủy phiếu đang chờ hoặc đã trả lại.")

    def _gs25_cancel(self, reason):
        self._gs25_lock_for_manager()
        self._gs25_check_cancel_state()
        if not (reason or "").strip():
            raise ValidationError("Vui lòng nhập lý do hủy.")
        return super(GS25DateCheckRecord, self).write({
            "state": "cancelled", "cancel_reason": reason.strip(),
            "cancelled_by_id": self.env.uid, "cancelled_date": fields.Datetime.now(),
        })

    def action_open_process_wizard(self):
        self._gs25_lock_for_manager()
        if self.state != "approved":
            raise ValidationError("Chỉ xử lý phiếu đã xác nhận.")
        return {"type": "ir.actions.act_window", "name": "Thực hiện xử lý",
                "res_model": "gs25.date.check.process.wizard", "view_mode": "form",
                "target": "new", "context": {"default_record_id": self.id}}

    # 14. THỰC HIỆN PHƯƠNG ÁN ĐÃ DUYỆT
    def _gs25_process(self, note=False, next_check_date=False):
        self._gs25_lock_for_manager()
        if self.state != "approved" or self.processed_date or self.scrap_ids:
            raise ValidationError("Phiếu không còn ở trạng thái có thể xử lý.")
        self._check_inspection_result()
        lot = self.lot_id
        qty = self.checked_quantity
        rounding = self.product_id.uom_id.rounding
        # Kiểm tra số lượng theo đơn vị tính của sản phẩm
        if not isfinite(qty) or qty <= 0 or rounding <= 0:
            raise ValidationError("Số lượng xử lý không hợp lệ.")
        if not isclose(qty / rounding, round(qty / rounding), rel_tol=0, abs_tol=1e-7):
            raise ValidationError("Số lượng xử lý phải phù hợp với đơn vị tính của sản phẩm.")
        if self.product_id.tracking == "serial" and qty != 1:
            raise ValidationError("Mỗi số serial chỉ được xử lý một sản phẩm.")

        # Khóa lô để tránh hai phiếu Date Check xử lý đồng thời
        lot.check_access("write")
        lot.flush_recordset()
        self.env.cr.execute(
            "SELECT id FROM stock_lot WHERE id = %s FOR UPDATE",
            (lot.id,),
        )
        lot.invalidate_recordset()
        lot.check_access("write")

        now = fields.Datetime.now()
        quants = lot._get_gs25_nvt_quants()
        quants.invalidate_recordset()
        self._check_inspection_result()
        if float_compare(qty, sum(quants.mapped("quantity")), precision_rounding=rounding) > 0:
            raise ValidationError("Số lượng xử lý vượt tồn kho hiện tại.")
        if float_compare(qty, 0, precision_rounding=rounding) <= 0:
            raise ValidationError("Số lượng xử lý không hợp lệ.")
        lot_vals = {"gs25_priority_quantity": 0, "gs25_monitor_quantity": 0,
                    "gs25_next_check_date": False, "gs25_last_handling_date": now,
                    "gs25_last_handling_user_id": self.env.uid}
        scraps = self.env["stock.scrap"]
        if self.proposed_action == "priority_sale":
            if not lot.expiration_date or lot.expiration_date <= now:
                raise ValidationError("Lô phải còn hạn sử dụng để ưu tiên bán.")
            lot_vals.update(gs25_handling_status="priority_sale", gs25_priority_quantity=qty)
        elif self.proposed_action == "monitor":
            next_check_date = fields.Datetime.to_datetime(next_check_date)
            if not next_check_date or next_check_date <= now:
                raise ValidationError("Thời điểm kiểm tra lại phải ở tương lai.")
            lot_vals.update(gs25_handling_status="monitor", gs25_monitor_quantity=qty,
                            gs25_next_check_date=next_check_date)
        elif self.proposed_action == "remove":
            if not (note or "").strip():
                raise ValidationError("Nhập ghi chú xác nhận loại bỏ thực tế.")
            scraps = self._gs25_create_scraps(quants, qty, rounding)
            lot_vals.update(gs25_handling_status="removed")
        else:
            raise ValidationError("Phương án xử lý không hợp lệ.")
        lot._gs25_update_handling(lot_vals)
        result = super(GS25DateCheckRecord, self).write({
            "state": "done", "processed_by_id": self.env.uid,
            "processed_date": now, "processed_quantity": qty,
            "processing_note": note, "next_check_date": next_check_date if self.proposed_action == "monitor" else False,
            "scrap_ids": [(6, 0, scraps.ids)],
        })

        self._gs25_notify_handling_result()
        return result

    def _gs25_notify_handling_result(self):
        self.ensure_one()
        if self.state != "done":
            return
        group_xmlid = "gs25_date_check.group_gs25_date_check_user"
        users = self.env["res.users"].sudo().search([
            ("active", "=", True), ("share", "=", False),
            ("id", "!=", self.env.uid),
            ("company_ids", "in", [self.env.company.id]),
        ])
        users = users.filtered(lambda user: user.has_group(group_xmlid)
                               and self.with_user(user).has_access("read"))
        actions = {"priority_sale": "Ưu tiên bán", "monitor": "Tiếp tục theo dõi",
                   "remove": "Đã loại bỏ hàng hóa"}
        for user in users:
            body = Markup("<p><strong>Phiếu %s đã được xử lý</strong></p>"
                          "<p>Sản phẩm: %s<br/>Số lô: %s<br/>"
                          "Phương án: %s<br/>Số lượng xử lý: %s %s<br/>"
                          "Người xử lý: %s</p>") % (
                self.name, self.product_id.display_name, self.lot_id.name,
                actions[self.proposed_action], self.processed_quantity,
                self.product_id.uom_id.name, self.processed_by_id.name,
            )
            if self.proposed_action == "monitor":
                body += Markup("<p>Kiểm tra lại lúc: %s</p>") % format_datetime(
                    self.env, self.next_check_date, tz=user.tz or "Asia/Ho_Chi_Minh",
                    dt_format="dd/MM/yyyy HH:mm", lang_code=user.lang or "vi_VN",
                )
            body += Markup('<p><a href="/web#id=%s&amp;model=gs25.date.check.record&amp;view_type=form">Xem chi tiết phiếu %s</a></p>') % (self.id, self.name)
            self.with_context(mail_notify_force_send=False).message_notify(
                partner_ids=user.partner_id.ids,
                subject="GS25 Date Check - Phiếu %s đã được xử lý" % self.name,
                body=body,
            )

    def _gs25_notify_monitor_reminder(self):
        self.ensure_one()
        lot = self.lot_id
        if (
            self.state != "done"
            or self.proposed_action != "monitor"
            or lot.gs25_handling_status != "monitor"
            or lot.gs25_reminder_sent
            or not lot.gs25_next_check_date
            or lot.gs25_next_check_date > fields.Datetime.now()
            or self.next_check_date != lot.gs25_next_check_date
            or self.processed_date != lot.gs25_last_handling_date
        ):
            return False

        quantity = sum(lot._get_gs25_nvt_quants().mapped("quantity"))
        if quantity <= 0:
            return False

        group_xmlid = "gs25_date_check.group_gs25_date_check_user"
        users = self.env["res.users"].sudo().search([
            ("active", "=", True), ("share", "=", False),
            ("company_ids", "in", [self.env.company.id]),
        ])
        users = users.filtered(lambda user: user.has_group(group_xmlid)
                               and self.with_user(user).has_access("read"))
        for user in users:
            body = Markup("<p><strong>Đến hạn kiểm tra lại hàng hóa</strong></p>"
                          "<p>Phiếu theo dõi: %s<br/>Sản phẩm: %s<br/>Số lô: %s<br/>"
                          "Số lượng theo dõi: %s %s<br/>Tồn kho hiện tại: %s %s<br/>"
                          "Thời điểm kiểm tra lại: %s</p>"
                          "<p>Vui lòng kiểm tra thực tế và lập phiếu kiểm tra mới.</p>") % (
                self.name, self.product_id.display_name, lot.name,
                lot.gs25_monitor_quantity, self.product_id.uom_id.name,
                quantity, self.product_id.uom_id.name,
                format_datetime(self.env, lot.gs25_next_check_date,
                                tz=user.tz or "Asia/Ho_Chi_Minh",
                                dt_format="dd/MM/yyyy HH:mm", lang_code=user.lang or "vi_VN"),
            )
            body += Markup('<p><a href="/web#id=%s&amp;model=gs25.date.check.record&amp;view_type=form">Xem chi tiết phiếu %s</a></p>') % (self.id, self.name)
            self.with_context(mail_notify_force_send=False).message_notify(
                partner_ids=user.partner_id.ids,
                subject="GS25 Date Check - Nhắc kiểm tra lại %s" % lot.name,
                body=body,
            )
        return bool(users)

    def _gs25_create_scraps(self, quants, qty, rounding):
        # Chỉ xử lý tồn khả dụng, không lấy hàng đã giữ chỗ.
        # Tạm giới hạn hàng không thuộc chủ sở hữu khác và không đóng kiện.
        from odoo.tools.float_utils import float_round
        Scrap = self.env["stock.scrap"]
        Scrap.check_access("create")
        if not self.env.user.has_group("stock.group_stock_user"):
            raise AccessError("Quản lý cần quyền Inventory để thực hiện loại bỏ hàng hóa.")

        # Khóa các quant hiện có trước khi tính tồn khả dụng
        if quants.ids:
            quants.flush_recordset()
            self.env.cr.execute(
                "SELECT id FROM stock_quant WHERE id IN %s ORDER BY id FOR UPDATE",
                (tuple(quants.ids),),
            )
            quants.invalidate_recordset()
        quants = self.lot_id._get_gs25_nvt_quants()
        quants.invalidate_recordset()
        plan = []
        remaining = qty
        for quant in quants.sorted("id"):
            if quant.owner_id or quant.package_id:
                continue
            available = max(0, quant.quantity - quant.reserved_quantity)
            take = float_round(min(remaining, available), precision_rounding=rounding, rounding_method="DOWN")
            if float_compare(take, 0, precision_rounding=rounding) <= 0:
                continue
            plan.append((quant.location_id.id, take))
            remaining -= take
            if float_compare(remaining, 0, precision_rounding=rounding) <= 0:
                break
        if float_compare(remaining, 0, precision_rounding=rounding) > 0:
            raise ValidationError("Không đủ tồn khả dụng không đóng kiện để loại bỏ.")
        if not isclose(sum(quantity for _, quantity in plan), qty, rel_tol=0, abs_tol=rounding * 1e-7):
            raise ValidationError("Tổng số lượng loại bỏ không khớp với phiếu kiểm tra.")
        scraps = Scrap
        for location_id, quantity in plan:
            scrap = Scrap.create({
                "product_id": self.product_id.id,
                "product_uom_id": self.product_id.uom_id.id,
                "lot_id": self.lot_id.id, "location_id": location_id,
                "scrap_qty": quantity, "company_id": self.env.company.id,
                "origin": self.name,
            })
            scrap.action_validate()
            if scrap.state != "done":
                raise ValidationError("Scrap chưa hoàn tất. Kiểm tra tồn kho và cấu hình Inventory.")
            scraps |= scrap
        return scraps

    def _gs25_lock_records(self, operation="write"):
        self.check_access(operation)
        if self.ids:
            self.flush_recordset()
            self.env.cr.execute("SELECT id FROM gs25_date_check_record WHERE id IN %s ORDER BY id FOR UPDATE", (tuple(self.ids),))
            self.invalidate_recordset()
            self.check_access(operation)

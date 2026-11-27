from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.float_utils import float_compare


GS25_DW_STATES = [
    ("not_sent", "Chưa gửi"),
    ("sent", "Đã gửi kho tổng"),
    ("received", "Kho tổng đã tiếp nhận"),
    ("confirmed", "Kho tổng xác nhận đủ hàng"),
    ("partial", "Kho tổng xác nhận một phần"),
    ("rejected", "Kho tổng từ chối"),
    ("shipping", "Kho tổng đang giao hàng"),
]


# A10-A11. ĐƠN ĐẶT HÀNG ĐIỆN TỬ GỬI KHO TỔNG (MÔ PHỎNG)
class GS25PurchaseOrder(models.Model):
    _name = "purchase.order"
    _inherit = ["purchase.order", "gs25.replenishment.mixin"]

    # 1. LIÊN KẾT PHIẾU ĐỀ XUẤT
    gs25_proposal_id = fields.Many2one(
        "gs25.replenishment.proposal",
        string="Phiếu đề xuất GS25",
        readonly=True,
        copy=False,
        index=True,
    )

    gs25_is_replenishment = fields.Boolean(
        string="Đơn đặt hàng bổ sung GS25",
        compute="_compute_gs25_is_replenishment",
        search="_search_gs25_is_replenishment",
    )

    # 2. TRẠNG THÁI PHÍA KHO TỔNG
    gs25_dw_state = fields.Selection(
        GS25_DW_STATES,
        string="Trạng thái kho tổng",
        default="not_sent",
        readonly=True,
        copy=False,
        tracking=True,
    )

    gs25_dw_sent_date = fields.Datetime(
        string="Thời điểm gửi kho tổng",
        readonly=True,
        copy=False,
    )

    gs25_dw_response_date = fields.Datetime(
        string="Thời điểm kho tổng phản hồi",
        readonly=True,
        copy=False,
    )

    gs25_dw_note = fields.Text(
        string="Phản hồi của kho tổng",
        readonly=True,
        copy=False,
    )

    gs25_dw_log_ids = fields.One2many(
        "gs25.replenishment.dw.log",
        "purchase_id",
        string="Lịch sử trạng thái kho tổng",
        readonly=True,
        copy=False,
    )

    @api.depends("gs25_proposal_id")
    def _compute_gs25_is_replenishment(self):
        for order in self:
            order.gs25_is_replenishment = bool(order.gs25_proposal_id)

    def _search_gs25_is_replenishment(self, operator, value):
        if operator not in ("=", "!=") or not isinstance(value, bool):
            return NotImplemented

        positive = value if operator == "=" else not value
        return [("gs25_proposal_id", "!=" if positive else "=", False)]

    def _gs25_protected_fields(self):
        return {
            "gs25_proposal_id", "gs25_dw_state", "gs25_dw_sent_date",
            "gs25_dw_response_date", "gs25_dw_note", "gs25_dw_log_ids",
        }

    # 3. KIỂM SOÁT CHỈNH SỬA
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("gs25_purchase_internal"):
            for vals in vals_list:
                if self._gs25_protected_fields().intersection(vals):
                    raise AccessError(
                        "Đơn đặt hàng GS25 chỉ được tạo từ phiếu đề xuất đã duyệt."
                    )

        return super().create(vals_list)

    def write(self, vals):
        if self._gs25_protected_fields().intersection(vals):
            raise AccessError(
                "Không được chỉnh sửa trực tiếp thông tin kho tổng. "
                "Vui lòng sử dụng các nút nghiệp vụ trên đơn."
            )

        gs25_orders = self.filtered("gs25_proposal_id")

        if gs25_orders and not self.env.context.get("gs25_purchase_internal"):
            if {"partner_id", "picking_type_id", "company_id"}.intersection(vals):
                raise AccessError(
                    "Không được đổi kho tổng hoặc kho nhận của đơn đặt hàng GS25."
                )

        return super().write(vals)

    def _gs25_write_internal(self, vals):
        return super(GS25PurchaseOrder, self).write(vals)

    def _gs25_log_dw_state(self, state, note=False):
        self.ensure_one()
        self.env["gs25.replenishment.dw.log"].sudo().create({
            "purchase_id": self.id,
            "state": state,
            "user_id": self.env.uid,
            "note": note,
        })

    def _gs25_check_replenishment_order(self):
        for order in self:
            if not order.gs25_proposal_id:
                raise ValidationError(
                    "Đơn %s không phải đơn đặt hàng bổ sung GS25." % order.name
                )

    # 4. A11. GỬI ĐƠN ĐẾN KHO TỔNG
    def action_gs25_send_to_central(self):
        self._gs25_check_replenishment_order()
        self._gs25_check_manager(
            "Chỉ quản lý cửa hàng mới được gửi đơn đến kho tổng."
        )
        self._gs25_lock_records()

        for order in self:
            if order.gs25_dw_state != "not_sent" or order.state not in (
                "draft", "sent",
            ):
                raise ValidationError(
                    "Đơn %s đã được gửi kho tổng hoặc không còn ở trạng thái báo giá."
                    % order.name
                )

            if not order.order_line.filtered(
                lambda line: not line.display_type and line.product_qty > 0
            ):
                raise ValidationError("Đơn %s chưa có sản phẩm." % order.name)

            # Xác nhận đơn mua chuẩn của Odoo để tạo phiếu nhập dự kiến tại NVT
            order.button_confirm()

            if order.state != "purchase":
                raise ValidationError(
                    "Đơn %s chưa được xác nhận (trạng thái: %s). "
                    "Vui lòng kiểm tra cấu hình phê duyệt Purchase."
                    % (order.name, dict(order._fields["state"].selection).get(order.state))
                )

            now = fields.Datetime.now()
            order._gs25_write_internal({
                "gs25_dw_state": "sent",
                "gs25_dw_sent_date": now,
            })
            order._gs25_log_dw_state("sent", "Cửa hàng gửi đơn đặt hàng điện tử.")
            order._gs25_notify_users(
                order._gs25_get_group_users(self._gs25_central_group),
                "GS25 - Đơn đặt hàng %s từ cửa hàng" % order.name,
                Markup(
                    "<p><strong>Cửa hàng gửi đơn đặt hàng %s</strong></p>"
                    "<p>Kho nhận: %s<br/>Số dòng: %s<br/>Phiếu đề xuất: %s</p>"
                ) % (
                    order.name,
                    order.picking_type_id.warehouse_id.display_name,
                    len(order.order_line),
                    order.gs25_proposal_id.name,
                ),
            )

        return True

    # 5. A11. MÔ PHỎNG PHẢN HỒI CỦA KHO TỔNG
    def _gs25_dw_transition(self, allowed_states, new_state, note=False):
        self._gs25_check_replenishment_order()
        self._gs25_check_central()
        self._gs25_lock_records()

        for order in self:
            if order.gs25_dw_state not in allowed_states:
                raise ValidationError(
                    "Đơn %s đang ở trạng thái '%s', không thể chuyển sang '%s'."
                    % (
                        order.name,
                        dict(GS25_DW_STATES).get(order.gs25_dw_state),
                        dict(GS25_DW_STATES).get(new_state),
                    )
                )

        vals = {"gs25_dw_state": new_state}

        if new_state != "shipping":
            vals["gs25_dw_response_date"] = fields.Datetime.now()

        if note:
            vals["gs25_dw_note"] = note

        for order in self:
            order._gs25_write_internal(vals)
            order._gs25_log_dw_state(new_state, note)
            order._gs25_notify_store_manager(new_state, note)

        return True

    def action_gs25_dw_receive(self):
        return self._gs25_dw_transition(
            ["sent"], "received", "Kho tổng đã tiếp nhận đơn.",
        )

    def action_gs25_dw_confirm(self):
        return self._gs25_dw_transition(
            ["received"], "confirmed", "Kho tổng xác nhận đáp ứng đủ số lượng.",
        )

    def action_gs25_dw_ship(self):
        return self._gs25_dw_transition(
            ["confirmed", "partial"], "shipping",
            "Kho tổng đã xuất hàng, đang giao đến cửa hàng.",
        )

    def action_gs25_open_dw_response_wizard(self):
        self.ensure_one()
        self._gs25_check_replenishment_order()
        self._gs25_check_central()
        mode = self.env.context.get("gs25_response_mode", "partial")

        if mode == "partial" and self.gs25_dw_state != "received":
            raise ValidationError(
                "Chỉ xác nhận một phần khi kho tổng đã tiếp nhận đơn."
            )

        if mode == "reject" and self.gs25_dw_state not in ("sent", "received"):
            raise ValidationError(
                "Chỉ từ chối đơn đã gửi hoặc đã tiếp nhận, chưa xác nhận giao."
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Xác nhận một phần" if mode == "partial" else "Từ chối đơn",
            "res_model": "gs25.dw.response.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_purchase_id": self.id,
                "default_mode": mode,
            },
        }

    def _gs25_dw_partial(self, quantities, note):
        """
        Kho tổng chỉ đáp ứng một phần.
        quantities: {purchase.order.line id: số lượng kho tổng đáp ứng}
        """
        self.ensure_one()
        note = (note or "").strip()

        if not note:
            raise ValidationError("Vui lòng nhập lý do kho tổng chỉ đáp ứng một phần.")

        self._gs25_check_central()
        self._gs25_lock_records()

        if self.gs25_dw_state != "received":
            raise ValidationError(
                "Chỉ xác nhận một phần khi kho tổng đã tiếp nhận đơn."
            )

        changed = False
        total = 0.0

        for line in self.order_line.filtered(lambda l: not l.display_type):
            new_qty = quantities.get(line.id, line.product_qty)
            rounding = line.product_uom_id.rounding

            if new_qty < 0 or float_compare(
                new_qty, line.product_qty, precision_rounding=rounding,
            ) > 0:
                raise ValidationError(
                    "Số lượng đáp ứng của %s phải từ 0 đến %s."
                    % (line.product_id.display_name, line.product_qty)
                )

            total += new_qty

            if float_compare(new_qty, line.product_qty, precision_rounding=rounding):
                changed = True

        if not changed:
            raise ValidationError(
                "Số lượng đáp ứng bằng số lượng đặt. "
                "Vui lòng dùng nút Xác nhận đủ hàng."
            )

        if total <= 0:
            raise ValidationError(
                "Kho tổng không đáp ứng sản phẩm nào. Vui lòng dùng nút Từ chối đơn."
            )

        was_locked = self.locked

        if was_locked:
            self.button_unlock()

        # Giảm số lượng trên đơn và trên phiếu nhập dự kiến tại NVT
        for line in self.order_line.filtered(lambda l: not l.display_type):
            new_qty = quantities.get(line.id, line.product_qty)

            if float_compare(
                new_qty, line.product_qty,
                precision_rounding=line.product_uom_id.rounding,
            ):
                line._gs25_reduce_incoming_moves(line.product_qty - new_qty)
                line.with_context(gs25_purchase_internal=True).write({
                    "product_qty": new_qty,
                })

        if was_locked:
            self.button_lock()

        return self._gs25_dw_transition(["received"], "partial", note)

    def _gs25_dw_reject(self, note):
        self.ensure_one()
        note = (note or "").strip()

        if not note:
            raise ValidationError("Vui lòng nhập lý do kho tổng từ chối đơn.")

        self._gs25_check_central()
        self._gs25_lock_records()

        if self.gs25_dw_state not in ("sent", "received"):
            raise ValidationError(
                "Chỉ từ chối đơn đã gửi hoặc đã tiếp nhận, chưa xác nhận giao."
            )

        if self.picking_ids.filtered(lambda picking: picking.state == "done"):
            raise ValidationError(
                "Đơn đã có phiếu nhập hoàn tất, không thể từ chối."
            )

        if self.locked:
            self.button_unlock()

        # Hủy đơn để hủy phiếu nhập dự kiến, sản phẩm được đề xuất lại ở lần kiểm tra sau
        self.button_cancel()
        return self._gs25_dw_transition(["sent", "received"], "rejected", note)

    def _gs25_notify_store_manager(self, state, note):
        self.ensure_one()
        body = Markup(
            "<p><strong>Đơn %s: %s</strong></p>"
            "<p>Phiếu đề xuất: %s</p>"
        ) % (
            self.name,
            dict(GS25_DW_STATES).get(state),
            self.gs25_proposal_id.name,
        )

        if note:
            body += Markup("<p>Ghi chú: %s</p>") % note

        users = self._gs25_get_group_users(self._gs25_manager_group)
        return self._gs25_notify_users(
            users,
            "GS25 - Đơn %s: %s" % (self.name, dict(GS25_DW_STATES).get(state)),
            body,
        )

    def action_gs25_view_proposal(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Phiếu đề xuất",
            "res_model": "gs25.replenishment.proposal",
            "res_id": self.gs25_proposal_id.id,
            "view_mode": "form",
        }


class GS25PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    gs25_proposal_line_id = fields.Many2one(
        "gs25.replenishment.proposal.line",
        string="Dòng đề xuất GS25",
        readonly=True,
        copy=False,
        index=True,
    )

    def _gs25_reduce_incoming_moves(self, reduce_qty):
        """
        Giảm nhu cầu nhập của các dịch chuyển chưa hoàn tất,
        để Odoo không tạo phiếu trả hàng cho phần kho tổng không giao.
        Phản hồi của kho tổng là mô phỏng nên cập nhật dịch chuyển bằng quyền hệ thống.
        """
        self.ensure_one()
        moves = self.move_ids.sudo().filtered(
            lambda move: move.state not in ("done", "cancel")
            and move.location_dest_id.usage != "supplier"
        ).sorted("id", reverse=True)

        remaining = self.product_uom_id._compute_quantity(
            reduce_qty, self.product_id.uom_id,
        )
        rounding = self.product_id.uom_id.rounding

        for move in moves:
            if float_compare(remaining, 0, precision_rounding=rounding) <= 0:
                break

            move_qty = move.product_uom._compute_quantity(
                move.product_uom_qty, self.product_id.uom_id,
            )
            take = min(move_qty, remaining)

            if float_compare(take, move_qty, precision_rounding=rounding) >= 0:
                move._action_cancel()
            else:
                move.product_uom_qty = self.product_id.uom_id._compute_quantity(
                    move_qty - take, move.product_uom,
                )

            remaining -= take

    def write(self, vals):
        if (
            not self.env.context.get("gs25_purchase_internal")
            and {"product_id", "product_qty", "product_uom_id"}.intersection(vals)
            and self.filtered(
                lambda line: line.order_id.gs25_proposal_id
                and line.order_id.gs25_dw_state != "not_sent"
            )
        ):
            raise AccessError(
                "Đơn đã gửi kho tổng, không được sửa sản phẩm hoặc số lượng."
            )

        return super().write(vals)


# NHẬT KÝ TRẠNG THÁI KHO TỔNG
class GS25ReplenishmentDwLog(models.Model):
    _name = "gs25.replenishment.dw.log"
    _description = "Nhật ký trạng thái kho tổng GS25"
    _order = "date desc, id desc"

    purchase_id = fields.Many2one(
        "purchase.order",
        string="Đơn đặt hàng",
        required=True,
        ondelete="cascade",
        index=True,
    )

    state = fields.Selection(
        GS25_DW_STATES,
        string="Trạng thái",
        required=True,
    )

    date = fields.Datetime(
        string="Thời điểm",
        default=fields.Datetime.now,
        required=True,
    )

    user_id = fields.Many2one(
        "res.users",
        string="Người thực hiện",
        required=True,
    )

    note = fields.Text(string="Ghi chú")

    def write(self, vals):
        raise AccessError("Không được chỉnh sửa nhật ký trạng thái kho tổng.")

    def unlink(self):
        if not self.env.context.get("gs25_allow_log_unlink"):
            raise AccessError("Không được xóa nhật ký trạng thái kho tổng.")
        return super().unlink()

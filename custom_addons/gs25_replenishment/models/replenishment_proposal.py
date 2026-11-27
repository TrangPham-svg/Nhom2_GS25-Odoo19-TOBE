from datetime import timedelta
from math import ceil, isfinite

from markupsafe import Markup

from odoo import Command, api, fields, models
from odoo.exceptions import AccessError, ValidationError
from odoo.tools.float_utils import float_compare, float_round


# A07. PHIẾU TỔNG HỢP ĐỀ XUẤT ĐẶT HÀNG BỔ SUNG
class GS25ReplenishmentProposal(models.Model):
    _name = "gs25.replenishment.proposal"
    _inherit = ["mail.thread", "gs25.replenishment.mixin"]
    _mail_post_access = "write"
    _description = "Phiếu đề xuất đặt hàng bổ sung GS25"
    _order = "proposal_date desc, id desc"

    _unique_name = models.Constraint(
        "UNIQUE(name)",
        "Mã phiếu đề xuất không được trùng.",
    )

    # 1. THÔNG TIN PHIẾU ĐỀ XUẤT
    name = fields.Char(
        string="Mã phiếu",
        default="Phiếu mới",
        required=True,
        readonly=True,
        copy=False,
    )

    proposal_date = fields.Datetime(
        string="Thời điểm kiểm tra tồn",
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
        required=True,
        readonly=True,
    )

    location_id = fields.Many2one(
        "stock.location",
        string="Vị trí tồn kho",
        related="warehouse_id.lot_stock_id",
        store=True,
    )

    requested_by_id = fields.Many2one(
        "res.users",
        string="Người lập đề xuất",
        default=lambda self: self.env.user,
        required=True,
        readonly=True,
    )

    source = fields.Selection(
        [
            ("manual", "Nhân viên kiểm tra"),
            ("cron", "Hệ thống tự động"),
        ],
        string="Nguồn đề xuất",
        default="manual",
        required=True,
        readonly=True,
    )

    state = fields.Selection(
        [
            ("draft", "Nháp"),
            ("waiting", "Chờ quản lý duyệt"),
            ("approved", "Đã duyệt"),
            ("ordered", "Đã tạo đơn đặt hàng"),
            ("rejected", "Bị từ chối"),
            ("cancelled", "Đã hủy"),
        ],
        string="Trạng thái",
        default="draft",
        required=True,
        readonly=True,
        copy=False,
        tracking=True,
    )

    line_ids = fields.One2many(
        "gs25.replenishment.proposal.line",
        "proposal_id",
        string="Sản phẩm đề xuất",
        copy=False,
    )

    note = fields.Text(
        string="Ghi chú của nhân viên",
        copy=False,
    )

    # 2. THAM SỐ TÍNH ĐỀ XUẤT (LƯU LẠI ĐỂ TRUY VẾT)
    sales_history_days = fields.Integer(
        string="Số ngày lấy dữ liệu bán",
        readonly=True,
    )

    lead_days = fields.Integer(
        string="Thời gian giao hàng (ngày)",
        readonly=True,
    )

    coverage_days = fields.Integer(
        string="Số ngày bán cần dự trữ",
        readonly=True,
    )

    # 3. THÔNG TIN DUYỆT CỦA QUẢN LÝ
    submitted_date = fields.Datetime(
        string="Thời điểm gửi duyệt",
        readonly=True,
        copy=False,
    )

    approved_by_id = fields.Many2one(
        "res.users",
        string="Quản lý duyệt",
        readonly=True,
        copy=False,
    )

    approved_date = fields.Datetime(
        string="Thời điểm duyệt",
        readonly=True,
        copy=False,
    )

    rejected_by_id = fields.Many2one(
        "res.users",
        string="Quản lý từ chối",
        readonly=True,
        copy=False,
    )

    rejected_date = fields.Datetime(
        string="Thời điểm từ chối",
        readonly=True,
        copy=False,
    )

    reject_reason = fields.Text(
        string="Lý do từ chối",
        readonly=True,
        copy=False,
    )

    manager_note = fields.Text(
        string="Ghi chú của quản lý",
        copy=False,
    )

    # 4. ĐƠN ĐẶT HÀNG ĐIỆN TỬ
    purchase_id = fields.Many2one(
        "purchase.order",
        string="Đơn đặt hàng",
        readonly=True,
        copy=False,
    )

    purchase_state = fields.Selection(
        related="purchase_id.state",
        string="Trạng thái đơn",
    )

    dw_state = fields.Selection(
        related="purchase_id.gs25_dw_state",
        string="Trạng thái kho tổng",
    )

    # 5. TỔNG HỢP
    line_count = fields.Integer(
        string="Số sản phẩm",
        compute="_compute_totals",
    )

    total_suggested_qty = fields.Float(
        string="Tổng SL đề xuất",
        compute="_compute_totals",
        digits="Product Unit",
    )

    total_approved_qty = fields.Float(
        string="Tổng SL duyệt",
        compute="_compute_totals",
        digits="Product Unit",
    )

    adjusted_line_count = fields.Integer(
        string="Số dòng quản lý điều chỉnh",
        compute="_compute_totals",
    )

    @api.depends(
        "line_ids.suggested_qty",
        "line_ids.approved_qty",
        "line_ids.is_adjusted",
    )
    def _compute_totals(self):
        for proposal in self:
            lines = proposal.line_ids
            proposal.line_count = len(lines)
            proposal.total_suggested_qty = sum(lines.mapped("suggested_qty"))
            proposal.total_approved_qty = sum(lines.mapped("approved_qty"))
            proposal.adjusted_line_count = len(lines.filtered("is_adjusted"))

    # 6. QUYỀN THAO TÁC TRÊN GIAO DIỆN
    can_edit_draft = fields.Boolean(compute="_compute_permissions")
    can_review = fields.Boolean(compute="_compute_permissions")

    @api.depends("state", "requested_by_id")
    @api.depends_context("uid")
    def _compute_permissions(self):
        is_manager = self._gs25_is_manager()

        for proposal in self:
            is_owner = proposal.requested_by_id.id == self.env.uid
            proposal.can_edit_draft = proposal.state == "draft" and (
                is_owner or is_manager
            )
            proposal.can_review = proposal.state == "waiting" and is_manager

    def _gs25_protected_fields(self):
        return {
            "name", "state", "proposal_date", "company_id", "warehouse_id",
            "requested_by_id", "source", "sales_history_days", "lead_days",
            "coverage_days", "submitted_date", "approved_by_id",
            "approved_date", "rejected_by_id", "rejected_date",
            "reject_reason", "purchase_id",
        }

    # 7. KIỂM SOÁT TẠO VÀ CHỈNH SỬA PHIẾU
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("gs25_proposal_internal"):
            raise AccessError(
                "Phiếu đề xuất được tạo tự động từ chức năng "
                "Kiểm tra tồn kho & tạo đề xuất."
            )

        for vals in vals_list:
            vals["state"] = "draft"
            vals["name"] = self.env.ref(
                "gs25_replenishment.seq_gs25_replenishment_proposal"
            ).sudo().next_by_id()

            if not vals["name"]:
                raise ValidationError("Không thể sinh mã phiếu đề xuất.")

        return super().create(vals_list)

    def write(self, vals):
        self._gs25_lock_records()

        if self._gs25_protected_fields().intersection(vals):
            raise AccessError(
                "Không được chỉnh sửa trực tiếp thông tin xử lý của phiếu đề xuất. "
                "Vui lòng sử dụng các nút nghiệp vụ trên phiếu."
            )

        is_manager = self._gs25_is_manager()

        for proposal in self:
            if proposal.state == "draft":
                if not (
                    proposal.requested_by_id.id == self.env.uid or is_manager
                ):
                    raise AccessError(
                        "Chỉ người lập hoặc quản lý mới được chỉnh sửa phiếu Nháp."
                    )

                if not set(vals).issubset({"note", "line_ids"}):
                    raise AccessError("Phiếu Nháp chỉ được cập nhật ghi chú.")

            elif proposal.state == "waiting":
                if not (is_manager and set(vals).issubset({
                    "manager_note", "line_ids",
                })):
                    raise AccessError(
                        "Phiếu đã gửi quản lý. Chỉ quản lý được điều chỉnh "
                        "số lượng và ghi chú duyệt."
                    )

            else:
                raise AccessError(
                    "Phiếu đề xuất đã được duyệt, từ chối hoặc hủy, "
                    "không được chỉnh sửa."
                )

        return super().write(vals)

    def _gs25_write_internal(self, vals):
        return super(GS25ReplenishmentProposal, self).write(vals)

    def unlink(self):
        self._gs25_lock_records("unlink")
        is_manager = self._gs25_is_manager()

        for proposal in self:
            if proposal.state not in ("draft", "cancelled"):
                raise AccessError(
                    "Chỉ được xóa phiếu đề xuất ở trạng thái Nháp hoặc Đã hủy."
                )

            if proposal.requested_by_id.id != self.env.uid and not is_manager:
                raise AccessError("Bạn chỉ được xóa phiếu do mình lập.")

        self.line_ids.with_context(gs25_proposal_line_internal=True).unlink()
        return super().unlink()

    # 8. A05. KIỂM TRA TỒN KHO VÀ PHÁT HIỆN SẢN PHẨM CẦN BỔ SUNG
    @api.model
    def _gs25_get_pending_product_ids(self, company):
        """
        Sản phẩm đang nằm trong đề xuất chưa kết thúc
        hoặc đơn đặt hàng chưa xác nhận, không đề xuất lặp lại.
        Đơn đã xác nhận được tính vào số lượng sắp nhập.
        """
        skip_id = self.env.context.get("gs25_skip_pending_proposal")
        proposals = self.sudo().search([
            ("company_id", "=", company.id),
            ("state", "in", ["draft", "waiting", "approved", "ordered"]),
            ("id", "!=", skip_id or 0),
        ])
        proposals = proposals.filtered(
            lambda proposal: proposal.state != "ordered"
            or proposal.purchase_id.state in ("draft", "sent", "to approve")
        )
        lines = proposals.line_ids
        return set(lines.product_id.ids)

    @api.model
    def _gs25_compute_suggested_qty(
        self,
        forecast_qty,
        min_qty,
        max_qty,
        avg_daily_sales,
        lead_days,
        coverage_days,
        pack_qty,
        rounding,
    ):
        """
        A06. Tính số lượng đề xuất đặt hàng.

        - Nhu cầu trong thời gian chờ hàng và dự trữ:
          bán TB/ngày x (thời gian giao + số ngày dự trữ)
        - Mức tồn mục tiêu = max(tồn tối đa, tồn tối thiểu + nhu cầu)
        - Số lượng cần đặt = mức mục tiêu - tồn dự báo,
          làm tròn lên theo bội số đặt hàng.
        """
        demand_qty = max(avg_daily_sales, 0.0) * (lead_days + coverage_days)
        target_qty = max(max_qty, min_qty + demand_qty)
        need_qty = target_qty - forecast_qty

        if float_compare(need_qty, 0, precision_rounding=rounding) <= 0:
            return 0.0

        if pack_qty and pack_qty > 0:
            need_qty = ceil(round(need_qty / pack_qty, 6)) * pack_qty

        return float_round(
            need_qty,
            precision_rounding=rounding,
            rounding_method="UP",
        )

    @api.model
    def _gs25_get_replenishment_candidates(self, company):
        warehouse = company._gs25_check_replenishment_config()
        store_location = warehouse.lot_stock_id

        orderpoints = self.env["stock.warehouse.orderpoint"].search([
            ("gs25_is_replenishment", "=", True),
            ("active", "=", True),
            ("company_id", "=", company.id),
            ("location_id", "child_of", store_location.id),
            ("product_id.active", "=", True),
        ], order="product_id")

        if not orderpoints:
            return []

        pending_product_ids = self._gs25_get_pending_product_ids(company)
        orderpoints = orderpoints.filtered(
            lambda op: op.product_id.id not in pending_product_ids
        )

        history_days = company.gs25_sales_history_days
        lead_days = company.gs25_lead_days
        coverage_days = company.gs25_coverage_days
        average_sales = self.env["gs25.pos.sale.import"]._gs25_get_average_daily_sales(
            orderpoints.product_id,
            history_days,
            company,
        )

        candidates = []

        for orderpoint in orderpoints:
            product = orderpoint.product_id.with_context(
                location=orderpoint.location_id.id,
            )
            rounding = product.uom_id.rounding
            forecast_qty = product.virtual_available

            # Chỉ đề xuất khi tồn dự báo bằng hoặc thấp hơn mức tối thiểu
            if float_compare(
                forecast_qty,
                orderpoint.product_min_qty,
                precision_rounding=rounding,
            ) > 0:
                continue

            avg_daily_sales = average_sales.get(product.id, 0.0)
            suggested_qty = self._gs25_compute_suggested_qty(
                forecast_qty,
                orderpoint.product_min_qty,
                orderpoint.product_max_qty,
                avg_daily_sales,
                lead_days,
                coverage_days,
                orderpoint.gs25_pack_qty,
                rounding,
            )

            if float_compare(suggested_qty, 0, precision_rounding=rounding) <= 0:
                continue

            candidates.append({
                "product_id": product.id,
                "orderpoint_id": orderpoint.id,
                "on_hand_qty": product.qty_available,
                "incoming_qty": product.incoming_qty,
                "outgoing_qty": product.outgoing_qty,
                "forecast_qty": forecast_qty,
                "min_qty": orderpoint.product_min_qty,
                "max_qty": orderpoint.product_max_qty,
                "pack_qty": orderpoint.gs25_pack_qty,
                "avg_daily_sales": avg_daily_sales,
                "suggested_qty": suggested_qty,
                "approved_qty": suggested_qty,
            })

        return candidates

    @api.model
    def _gs25_generate_proposal(self, company=None, source="manual"):
        """A05-A07. Kiểm tra tồn kho và lập phiếu tổng hợp đề xuất."""
        company = company or self.env.company
        warehouse = company._gs25_check_replenishment_config()

        # Khóa theo công ty để hai lần kiểm tra cùng lúc không tạo phiếu trùng
        self.env.cr.execute(
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (250001, company.id),
        )

        candidates = self._gs25_get_replenishment_candidates(company)

        if not candidates:
            return self.browse()

        proposal = self.with_context(gs25_proposal_internal=True).create({
            "company_id": company.id,
            "warehouse_id": warehouse.id,
            "source": source,
            "sales_history_days": company.gs25_sales_history_days,
            "lead_days": company.gs25_lead_days,
            "coverage_days": company.gs25_coverage_days,
            "line_ids": [Command.create(vals) for vals in candidates],
        })

        proposal.message_post(body=Markup(
            "<p><strong>Đã kiểm tra tồn kho tại %s</strong></p>"
            "<p>Số sản phẩm cần bổ sung: %s<br/>Tổng số lượng đề xuất: %s</p>"
        ) % (
            warehouse.lot_stock_id.complete_name,
            proposal.line_count,
            proposal.total_suggested_qty,
        ))
        return proposal

    @api.model
    def action_gs25_generate_proposal(self):
        if not self.env.user.has_group(self._gs25_user_group):
            raise AccessError(
                "Bạn không có quyền kiểm tra tồn kho và lập đề xuất đặt hàng."
            )

        proposal = self._gs25_generate_proposal()

        if not proposal:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": "Không có sản phẩm cần bổ sung",
                    "message": "Tồn kho dự báo của các sản phẩm đều cao hơn "
                               "mức tối thiểu, hoặc sản phẩm đang có đề xuất "
                               "chưa xử lý.",
                    "type": "info",
                    "sticky": False,
                },
            }

        return {
            "type": "ir.actions.act_window",
            "name": "Phiếu đề xuất đặt hàng",
            "res_model": self._name,
            "res_id": proposal.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def _gs25_cron_generate_proposals(self):
        companies = self.env["res.company"].search([
            ("gs25_auto_check", "=", True),
        ])

        for company in companies:
            if not company._gs25_get_store_warehouse():
                continue

            proposal = self.with_company(company)._gs25_generate_proposal(
                company,
                source="cron",
            )

            if proposal:
                users = proposal._gs25_get_group_users(
                    self._gs25_user_group,
                    exclude_current=False,
                )
                proposal._gs25_notify_users(
                    users,
                    "GS25 - Có sản phẩm cần đặt hàng bổ sung",
                    Markup(
                        "<p><strong>Hệ thống phát hiện %s sản phẩm "
                        "dưới mức tồn tối thiểu.</strong></p>"
                        "<p>Phiếu %s đã được lập. Vui lòng kiểm tra "
                        "và gửi quản lý duyệt.</p>"
                    ) % (proposal.line_count, proposal.name),
                )

    def action_refresh_lines(self):
        """Cập nhật lại số liệu tồn kho của phiếu Nháp trước khi gửi duyệt."""
        self._gs25_lock_records()

        for proposal in self:
            if not proposal.can_edit_draft:
                raise AccessError(
                    "Chỉ cập nhật số liệu cho phiếu Nháp của bạn."
                )

            candidates = {
                vals["product_id"]: vals
                for vals in proposal._gs25_get_replenishment_candidates_for_refresh()
            }
            lines = proposal.line_ids.with_context(gs25_proposal_line_internal=True)

            for line in lines:
                vals = candidates.get(line.product_id.id)

                if vals:
                    line.write(vals)
                else:
                    line.unlink()

            proposal.message_post(body="Đã cập nhật lại số liệu tồn kho.")

        return True

    def _gs25_get_replenishment_candidates_for_refresh(self):
        """Tính lại đề xuất, không coi sản phẩm của chính phiếu này là đang chờ."""
        self.ensure_one()
        return self.with_context(
            gs25_skip_pending_proposal=self.id,
        )._gs25_get_replenishment_candidates(self.company_id)

    # 9. GỬI QUẢN LÝ DUYỆT
    def action_submit(self):
        self._gs25_lock_records()

        for proposal in self:
            if proposal.state != "draft":
                raise ValidationError(
                    "Chỉ có thể gửi phiếu đang ở trạng thái Nháp."
                )

            if not proposal.can_edit_draft:
                raise AccessError(
                    "Chỉ người lập hoặc quản lý mới được gửi phiếu đề xuất."
                )

            if not proposal.line_ids:
                raise ValidationError(
                    "Phiếu đề xuất chưa có sản phẩm nào.\n\n"
                    "Vui lòng kiểm tra lại tồn kho trước khi gửi quản lý."
                )

            proposal._gs25_write_internal({
                "state": "waiting",
                "submitted_date": fields.Datetime.now(),
            })

            proposal._gs25_notify_users(
                proposal._gs25_get_group_users(self._gs25_manager_group),
                "GS25 - Phiếu đề xuất %s chờ duyệt" % proposal.name,
                Markup(
                    "<p><strong>Phiếu đề xuất %s cần quản lý duyệt</strong></p>"
                    "<p>Người lập: %s<br/>Số sản phẩm: %s<br/>"
                    "Tổng số lượng đề xuất: %s</p>"
                ) % (
                    proposal.name,
                    proposal.requested_by_id.name,
                    proposal.line_count,
                    proposal.total_suggested_qty,
                ),
            )

        return True

    # 10. A09. QUẢN LÝ XÁC NHẬN ĐỀ XUẤT
    def action_approve(self):
        self._gs25_lock_records()
        self._gs25_check_manager(
            "Chỉ quản lý cửa hàng mới được duyệt phiếu đề xuất."
        )

        for proposal in self:
            if proposal.state != "waiting":
                raise ValidationError(
                    "Chỉ có thể duyệt phiếu đang chờ quản lý."
                )

            proposal.line_ids._gs25_check_approved_qty()

            if not proposal.line_ids.filtered(
                lambda line: float_compare(
                    line.approved_qty, 0,
                    precision_rounding=line.uom_id.rounding,
                ) > 0
            ):
                raise ValidationError(
                    "Tất cả sản phẩm đều có số lượng duyệt bằng 0.\n\n"
                    "Nếu không cần đặt hàng, vui lòng chọn Từ chối đề xuất."
                )

            proposal._gs25_write_internal({
                "state": "approved",
                "approved_by_id": self.env.uid,
                "approved_date": fields.Datetime.now(),
            })
            proposal._gs25_notify_requester(
                "đã được duyệt",
                Markup("<p>Tổng số lượng duyệt: %s<br/>Số dòng điều chỉnh: %s</p>")
                % (proposal.total_approved_qty, proposal.adjusted_line_count),
            )

        return True

    def action_open_reject_wizard(self):
        self.ensure_one()
        self._gs25_check_manager(
            "Chỉ quản lý cửa hàng mới được từ chối phiếu đề xuất."
        )

        if self.state != "waiting":
            raise ValidationError("Chỉ từ chối phiếu đang chờ quản lý duyệt.")

        return {
            "type": "ir.actions.act_window",
            "name": "Từ chối đề xuất",
            "res_model": "gs25.replenishment.reject.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_proposal_id": self.id},
        }

    def _gs25_reject(self, reason):
        self.ensure_one()
        self._gs25_lock_records()
        self._gs25_check_manager(
            "Chỉ quản lý cửa hàng mới được từ chối phiếu đề xuất."
        )

        if self.state != "waiting":
            raise ValidationError("Chỉ từ chối phiếu đang chờ quản lý duyệt.")

        reason = (reason or "").strip()

        if not reason:
            raise ValidationError("Vui lòng nhập lý do từ chối đề xuất.")

        self._gs25_write_internal({
            "state": "rejected",
            "reject_reason": reason,
            "rejected_by_id": self.env.uid,
            "rejected_date": fields.Datetime.now(),
        })
        self._gs25_notify_requester(
            "bị từ chối",
            Markup("<p>Lý do: %s</p>") % reason,
        )
        return True

    def action_cancel(self):
        self._gs25_lock_records()

        for proposal in self:
            if proposal.state != "draft" or not proposal.can_edit_draft:
                raise ValidationError(
                    "Chỉ hủy được phiếu Nháp do bạn lập hoặc khi bạn là quản lý."
                )

            proposal._gs25_write_internal({"state": "cancelled"})

        return True

    def _gs25_notify_requester(self, result, extra_body):
        self.ensure_one()

        if self.requested_by_id.id == self.env.uid:
            return False

        body = Markup(
            "<p><strong>Phiếu đề xuất %s %s</strong></p>"
            "<p>Quản lý: %s</p>"
        ) % (self.name, result, self.env.user.name) + extra_body

        return self._gs25_notify_users(
            self.requested_by_id,
            "GS25 - Phiếu đề xuất %s %s" % (self.name, result),
            body,
        )

    # 11. A10. TẠO ĐƠN ĐẶT HÀNG ĐIỆN TỬ
    def action_create_purchase_order(self):
        self.ensure_one()
        self._gs25_lock_records()
        self._gs25_check_manager(
            "Chỉ quản lý cửa hàng mới được tạo đơn đặt hàng."
        )

        if self.state != "approved" or self.purchase_id:
            raise ValidationError(
                "Chỉ tạo đơn đặt hàng cho phiếu đã duyệt và chưa có đơn."
            )

        partner = self.company_id._gs25_get_central_partner()

        if not partner:
            raise ValidationError(
                "Chưa cấu hình kho tổng nhận đơn đặt hàng.\n\n"
                "Vui lòng chọn đối tác kho tổng tại menu Cấu hình."
            )

        picking_type = self.warehouse_id.in_type_id

        if not picking_type:
            raise ValidationError(
                "Kho %s chưa có loại hoạt động nhập kho."
                % self.warehouse_id.display_name
            )

        lines = self.line_ids.filtered(
            lambda line: float_compare(
                line.approved_qty, 0,
                precision_rounding=line.uom_id.rounding,
            ) > 0
        )

        if not lines:
            raise ValidationError("Không có sản phẩm nào để đặt hàng.")

        planned_date = fields.Datetime.now() + timedelta(days=self.lead_days)
        purchase = self.env["purchase.order"].with_context(
            gs25_purchase_internal=True,
        ).create({
            "partner_id": partner.id,
            "company_id": self.company_id.id,
            "picking_type_id": picking_type.id,
            "origin": self.name,
            "gs25_proposal_id": self.id,
            "order_line": [
                Command.create({
                    "product_id": line.product_id.id,
                    "product_qty": line.approved_qty,
                    "product_uom_id": line.product_id.uom_id.id,
                    "date_planned": planned_date,
                    "gs25_proposal_line_id": line.id,
                })
                for line in lines
            ],
        })

        self._gs25_write_internal({
            "state": "ordered",
            "purchase_id": purchase.id,
        })

        self.message_post(body=Markup(
            "<p>Đã tạo đơn đặt hàng điện tử <strong>%s</strong> "
            "gửi %s.</p>"
        ) % (purchase.name, partner.display_name))

        return self.action_view_purchase_order()

    def action_view_purchase_order(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Đơn đặt hàng",
            "res_model": "purchase.order",
            "res_id": self.purchase_id.id,
            "view_mode": "form",
            "target": "current",
        }


# DÒNG SẢN PHẨM ĐỀ XUẤT
class GS25ReplenishmentProposalLine(models.Model):
    _name = "gs25.replenishment.proposal.line"
    _description = "Dòng đề xuất đặt hàng bổ sung GS25"
    _order = "proposal_id desc, product_id, id"

    _unique_product = models.Constraint(
        "UNIQUE(proposal_id, product_id)",
        "Mỗi sản phẩm chỉ xuất hiện một lần trên phiếu đề xuất.",
    )

    proposal_id = fields.Many2one(
        "gs25.replenishment.proposal",
        string="Phiếu đề xuất",
        required=True,
        ondelete="cascade",
        index=True,
    )

    proposal_state = fields.Selection(
        related="proposal_id.state",
        string="Trạng thái phiếu",
        store=True,
    )

    company_id = fields.Many2one(
        related="proposal_id.company_id",
        store=True,
    )

    proposal_date = fields.Datetime(
        related="proposal_id.proposal_date",
        store=True,
        string="Ngày đề xuất",
    )

    product_id = fields.Many2one(
        "product.product",
        string="Sản phẩm",
        required=True,
        readonly=True,
        index=True,
    )

    uom_id = fields.Many2one(
        "uom.uom",
        related="product_id.uom_id",
        string="Đơn vị",
    )

    orderpoint_id = fields.Many2one(
        "stock.warehouse.orderpoint",
        string="Mức tồn áp dụng",
        readonly=True,
        ondelete="set null",
    )

    # 1. A05. SỐ LIỆU TỒN KHO TẠI THỜI ĐIỂM KIỂM TRA
    on_hand_qty = fields.Float(string="Tồn hiện có", digits="Product Unit", readonly=True)
    incoming_qty = fields.Float(string="Sắp nhập", digits="Product Unit", readonly=True)
    outgoing_qty = fields.Float(string="Sắp xuất", digits="Product Unit", readonly=True)
    forecast_qty = fields.Float(string="Tồn dự báo", digits="Product Unit", readonly=True)
    min_qty = fields.Float(string="Tồn tối thiểu", digits="Product Unit", readonly=True)
    max_qty = fields.Float(string="Tồn tối đa", digits="Product Unit", readonly=True)
    pack_qty = fields.Float(string="Bội số đặt", digits="Product Unit", readonly=True)
    avg_daily_sales = fields.Float(
        string="Bán TB/ngày",
        digits="Product Unit",
        readonly=True,
    )

    # 2. A06. SỐ LƯỢNG HỆ THỐNG ĐỀ XUẤT
    suggested_qty = fields.Float(
        string="SL đề xuất",
        digits="Product Unit",
        readonly=True,
    )

    # 3. A08. QUẢN LÝ KIỂM TRA VÀ ĐIỀU CHỈNH
    approved_qty = fields.Float(
        string="SL duyệt",
        digits="Product Unit",
    )

    adjust_reason = fields.Char(string="Lý do điều chỉnh")

    is_adjusted = fields.Boolean(
        string="Đã điều chỉnh",
        compute="_compute_is_adjusted",
        store=True,
    )

    purchase_line_ids = fields.One2many(
        "purchase.order.line",
        "gs25_proposal_line_id",
        string="Dòng đơn đặt hàng",
        readonly=True,
    )

    @api.depends("suggested_qty", "approved_qty", "uom_id")
    def _compute_is_adjusted(self):
        for line in self:
            line.is_adjusted = bool(float_compare(
                line.approved_qty,
                line.suggested_qty,
                precision_rounding=line.uom_id.rounding or 0.01,
            ))

    def _gs25_check_approved_qty(self):
        for line in self:
            rounding = line.uom_id.rounding or 0.01

            if not isfinite(line.approved_qty) or line.approved_qty < 0:
                raise ValidationError(
                    "Số lượng duyệt của %s không hợp lệ."
                    % line.product_id.display_name
                )

            if float_compare(
                line.approved_qty,
                line.uom_id.round(line.approved_qty),
                precision_rounding=rounding,
            ) != 0:
                raise ValidationError(
                    "Số lượng duyệt của %s không phù hợp đơn vị tính."
                    % line.product_id.display_name
                )

            if line.is_adjusted and not (line.adjust_reason or "").strip():
                raise ValidationError(
                    "Bạn chưa nhập lý do điều chỉnh cho sản phẩm %s.\n\n"
                    "Số lượng duyệt (%s) khác số lượng hệ thống đề xuất (%s)."
                    % (
                        line.product_id.display_name,
                        line.approved_qty,
                        line.suggested_qty,
                    )
                )

    @api.constrains("approved_qty")
    def _check_approved_qty_value(self):
        for line in self:
            if not isfinite(line.approved_qty) or line.approved_qty < 0:
                raise ValidationError(
                    "Số lượng duyệt của %s không được âm."
                    % line.product_id.display_name
                )

    # 4. KIỂM SOÁT CHỈNH SỬA DÒNG ĐỀ XUẤT
    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("gs25_proposal_internal"):
            raise AccessError(
                "Dòng đề xuất được hệ thống tạo từ kết quả kiểm tra tồn kho."
            )
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get("gs25_proposal_line_internal"):
            return super().write(vals)

        if not set(vals).issubset({"approved_qty", "adjust_reason"}):
            raise AccessError(
                "Chỉ được điều chỉnh số lượng duyệt và lý do điều chỉnh."
            )

        is_manager = self.env.user.has_group(
            "gs25_replenishment.group_gs25_replenishment_manager"
        )

        for line in self:
            if line.proposal_id.state != "waiting" or not is_manager:
                raise AccessError(
                    "Chỉ quản lý được điều chỉnh số lượng "
                    "khi phiếu đang chờ duyệt."
                )

        self.proposal_id._gs25_lock_records()
        result = super().write(vals)

        for line in self:
            line.proposal_id.message_post(body=Markup(
                "Điều chỉnh <strong>%s</strong>: SL duyệt %s "
                "(hệ thống đề xuất %s). Lý do: %s"
            ) % (
                line.product_id.display_name,
                line.approved_qty,
                line.suggested_qty,
                line.adjust_reason or "-",
            ))

        return result

    def unlink(self):
        if not self.env.context.get("gs25_proposal_line_internal"):
            for line in self:
                if not line.proposal_id.can_edit_draft:
                    raise AccessError(
                        "Chỉ được bỏ sản phẩm khỏi phiếu đề xuất ở trạng thái Nháp."
                    )
        return super().unlink()

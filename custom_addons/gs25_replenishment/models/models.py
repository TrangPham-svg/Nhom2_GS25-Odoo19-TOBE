from markupsafe import Markup
from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


# A01. CẤU HÌNH INVENTORY VÀ PURCHASE LIÊN QUAN ĐẾN ĐẶT HÀNG
class GS25ResCompany(models.Model):
    _inherit = "res.company"

    # 1. KHO CỬA HÀNG VÀ KHO TỔNG
    gs25_store_warehouse_id = fields.Many2one(
        "stock.warehouse",
        string="Kho cửa hàng GS25",
        help="Kho của cửa hàng nhận hàng bổ sung. "
             "Để trống sẽ tự tìm kho có mã NVT.",
    )

    gs25_central_partner_id = fields.Many2one(
        "res.partner",
        string="Kho tổng (nhà cung cấp mô phỏng)",
        help="Đối tác đại diện cho kho tổng GS25. "
             "Đơn đặt hàng điện tử được gửi đến đối tác này.",
    )

    # 2. THAM SỐ TÍNH ĐỀ XUẤT ĐẶT HÀNG
    gs25_sales_history_days = fields.Integer(
        string="Số ngày lấy dữ liệu bán hàng",
        default=7,
        help="Số ngày gần nhất dùng để tính sản lượng bán trung bình mỗi ngày.",
    )

    gs25_lead_days = fields.Integer(
        string="Thời gian giao hàng (ngày)",
        default=1,
        help="Số ngày từ khi gửi đơn đến khi kho tổng giao hàng.",
    )

    gs25_coverage_days = fields.Integer(
        string="Số ngày bán cần dự trữ",
        default=2,
        help="Số ngày bán hàng cần đảm bảo sau khi nhận hàng bổ sung.",
    )

    gs25_auto_check = fields.Boolean(
        string="Tự động kiểm tra tồn kho hằng ngày",
        default=True,
    )

    gs25_config_warning = fields.Html(
        string="Kết quả kiểm tra cấu hình",
        compute="_compute_gs25_config_warning",
        sanitize=False,
    )

    @api.constrains(
        "gs25_sales_history_days",
        "gs25_lead_days",
        "gs25_coverage_days",
    )
    def _check_gs25_replenishment_days(self):
        for company in self:
            if company.gs25_sales_history_days <= 0:
                raise ValidationError(
                    "Số ngày lấy dữ liệu bán hàng phải lớn hơn 0."
                )
            if company.gs25_lead_days < 0 or company.gs25_coverage_days < 0:
                raise ValidationError(
                    "Thời gian giao hàng và số ngày dự trữ không được âm."
                )

    # 3. TRUY XUẤT CẤU HÌNH
    def _gs25_get_store_warehouse(self):
        """Kho cửa hàng: lấy theo cấu hình, nếu chưa có thì tìm kho mã NVT."""
        self.ensure_one()

        if self.gs25_store_warehouse_id:
            return self.gs25_store_warehouse_id

        return self.env["stock.warehouse"].search([
            ("code", "=", "NVT"),
            ("company_id", "=", self.id),
        ], limit=1)

    def _gs25_get_store_location(self):
        """Vị trí tồn kho của cửa hàng (NVT/Tồn kho)."""
        self.ensure_one()
        return self._gs25_get_store_warehouse().lot_stock_id

    def _gs25_get_central_partner(self):
        """Đối tác kho tổng: lấy theo cấu hình hoặc đối tác mặc định của module."""
        self.ensure_one()

        if self.gs25_central_partner_id:
            return self.gs25_central_partner_id

        return self.env.ref(
            "gs25_replenishment.res_partner_gs25_central_warehouse",
            raise_if_not_found=False,
        ) or self.env["res.partner"]

    def _gs25_get_customer_location(self):
        return self.env.ref(
            "stock.stock_location_customers",
            raise_if_not_found=False,
        ) or self.env["stock.location"].search([
            ("usage", "=", "customer"),
        ], limit=1)

    def _gs25_check_replenishment_config(self):
        """
        Kiểm tra đủ cấu hình Inventory và Purchase
        trước khi import bán hàng hoặc tạo đơn đặt hàng.
        """
        self.ensure_one()

        warehouse = self._gs25_get_store_warehouse()

        if not warehouse:
            raise ValidationError(
                "Chưa cấu hình kho cửa hàng GS25.\n\n"
                "Vui lòng tạo kho có mã NVT hoặc chọn kho cửa hàng "
                "tại menu Đặt hàng bổ sung > Cấu hình."
            )

        if not warehouse.lot_stock_id:
            raise ValidationError(
                "Kho %s chưa có vị trí tồn kho." % warehouse.display_name
            )

        if not warehouse.in_type_id or not warehouse.out_type_id:
            raise ValidationError(
                "Kho %s chưa có loại hoạt động Nhập kho/Xuất kho."
                % warehouse.display_name
            )

        return warehouse

    @api.depends(
        "gs25_store_warehouse_id",
        "gs25_central_partner_id",
    )
    def _compute_gs25_config_warning(self):
        for company in self:
            warehouse = company._gs25_get_store_warehouse()
            partner = company._gs25_get_central_partner()
            items = []

            def add(ok, label):
                items.append(Markup("<li>%s %s</li>") % (
                    "✅" if ok else "❌", label,
                ))

            add(bool(warehouse), "Kho cửa hàng: %s" % (
                warehouse.display_name if warehouse else "chưa có kho mã NVT"
            ))
            add(bool(warehouse.lot_stock_id), "Vị trí tồn kho: %s" % (
                warehouse.lot_stock_id.complete_name or "chưa có"
            ))
            add(bool(warehouse.in_type_id), "Loại hoạt động nhập kho: %s" % (
                warehouse.in_type_id.display_name or "chưa có"
            ))
            add(bool(warehouse.out_type_id), "Loại hoạt động xuất bán: %s" % (
                warehouse.out_type_id.display_name or "chưa có"
            ))
            add(bool(partner), "Kho tổng nhận đơn: %s" % (
                partner.display_name if partner else "chưa có"
            ))
            add(bool(company._gs25_get_customer_location()),
                "Vị trí khách hàng cho bán hàng POS")

            company.gs25_config_warning = (
                Markup("<ul class='list-unstyled mb-0'>")
                + Markup("").join(items)
                + Markup("</ul>")
            )

    # 4. MỞ MÀN HÌNH CẤU HÌNH CỦA CÔNG TY HIỆN TẠI
    @api.model
    def action_gs25_open_replenishment_config(self):
        if not self.env.user.has_group("base.group_system"):
            raise AccessError(
                "Chỉ quản trị hệ thống mới được cấu hình đặt hàng bổ sung."
            )

        return {
            "type": "ir.actions.act_window",
            "name": "Cấu hình đặt hàng bổ sung",
            "res_model": "res.company",
            "res_id": self.env.company.id,
            "view_mode": "form",
            "views": [(
                self.env.ref(
                    "gs25_replenishment.view_res_company_gs25_replenishment_form"
                ).id,
                "form",
            )],
            "target": "current",
        }


# CÁC HÀM DÙNG CHUNG CHO NGHIỆP VỤ ĐẶT HÀNG BỔ SUNG
class GS25ReplenishmentMixin(models.AbstractModel):
    _name = "gs25.replenishment.mixin"
    _description = "Hàm dùng chung GS25 Replenishment"

    _gs25_user_group = "gs25_replenishment.group_gs25_replenishment_user"
    _gs25_manager_group = "gs25_replenishment.group_gs25_replenishment_manager"
    _gs25_central_group = "gs25_replenishment.group_gs25_replenishment_central"

    # 1. KIỂM TRA QUYỀN
    def _gs25_is_manager(self):
        return self.env.user.has_group(self._gs25_manager_group)

    def _gs25_check_manager(self, message=None):
        if not self._gs25_is_manager():
            raise AccessError(
                message or "Chỉ quản lý cửa hàng mới được thực hiện thao tác này."
            )

    def _gs25_check_central(self, message=None):
        if not self.env.user.has_group(self._gs25_central_group):
            raise AccessError(
                message or "Chỉ người dùng kho tổng (mô phỏng) "
                           "mới được thực hiện thao tác này."
            )

    # 2. KHÓA BẢN GHI KHI XỬ LÝ ĐỒNG THỜI
    def _gs25_lock_records(self, operation="write"):
        self.check_access(operation)

        if self.ids:
            self.flush_recordset()
            self.env.cr.execute(
                'SELECT id FROM "%s" WHERE id IN %%s ORDER BY id FOR UPDATE'
                % self._table,
                (tuple(self.ids),),
            )
            self.invalidate_recordset()
            self.check_access(operation)

    # 3. GỬI THÔNG BÁO CHO NHÓM NGƯỜI DÙNG
    def _gs25_get_group_users(self, group_xmlid, exclude_current=True):
        domain = [
            ("active", "=", True),
            ("share", "=", False),
            ("company_ids", "in", [self.env.company.id]),
        ]

        if exclude_current:
            domain.append(("id", "!=", self.env.uid))

        users = self.env["res.users"].sudo().search(domain)

        return users.filtered(
            lambda user: user.has_group(group_xmlid)
            and self.with_user(user).has_access("read")
        )

    def _gs25_notify_users(self, users, subject, body):
        self.ensure_one()

        users = users.filtered(lambda user: user.partner_id)

        if not users:
            return False

        link = Markup(
            '<p><a href="/web#id=%s&amp;model=%s&amp;view_type=form">'
            'Xem chi tiết %s</a></p>'
        ) % (self.id, self._name, self.display_name)

        self.with_context(mail_notify_force_send=False).message_notify(
            partner_ids=users.partner_id.ids,
            subject=subject,
            body=body + link,
        )
        return True

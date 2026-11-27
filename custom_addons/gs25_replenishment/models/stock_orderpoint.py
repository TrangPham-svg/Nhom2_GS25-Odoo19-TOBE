from math import isfinite

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


# A04. THIẾT LẬP MỨC TỒN KHO TỐI THIỂU
class GS25StockWarehouseOrderpoint(models.Model):
    _inherit = "stock.warehouse.orderpoint"

    # 1. THÔNG TIN MỨC TỒN GS25
    gs25_is_replenishment = fields.Boolean(
        string="Áp dụng đặt hàng GS25",
        default=False,
        copy=False,
        help="Mức tồn được dùng để phát hiện sản phẩm cần bổ sung "
             "và lập phiếu đề xuất đặt hàng GS25.",
    )

    gs25_pack_qty = fields.Float(
        string="Bội số đặt hàng",
        digits="Product Unit",
        default=1.0,
        help="Số lượng đề xuất được làm tròn lên theo bội số này "
             "(ví dụ: 1 thùng = 24 chai).",
    )

    gs25_note = fields.Char(string="Ghi chú GS25")

    # 2. KIỂM TRA DỮ LIỆU
    @api.constrains(
        "gs25_is_replenishment",
        "gs25_pack_qty",
        "product_min_qty",
        "product_max_qty",
        "location_id",
    )
    def _check_gs25_replenishment_level(self):
        for orderpoint in self.filtered("gs25_is_replenishment"):
            if (
                not isfinite(orderpoint.product_min_qty)
                or orderpoint.product_min_qty < 0
            ):
                raise ValidationError(
                    "Mức tồn tối thiểu của %s không được âm."
                    % orderpoint.product_id.display_name
                )

            if (
                not isfinite(orderpoint.gs25_pack_qty)
                or orderpoint.gs25_pack_qty <= 0
            ):
                raise ValidationError(
                    "Bội số đặt hàng của %s phải lớn hơn 0."
                    % orderpoint.product_id.display_name
                )

            if orderpoint.product_max_qty < orderpoint.product_min_qty:
                raise ValidationError(
                    "Mức tồn tối đa của %s phải lớn hơn hoặc bằng mức tối thiểu."
                    % orderpoint.product_id.display_name
                )

            store_location = orderpoint.company_id._gs25_get_store_location()

            if store_location and not orderpoint.location_id._child_of(store_location):
                raise ValidationError(
                    "Mức tồn GS25 của %s phải thuộc vị trí %s."
                    % (
                        orderpoint.product_id.display_name,
                        store_location.complete_name,
                    )
                )

    # 3. LUÔN DÙNG CHẾ ĐỘ THỦ CÔNG
    # Mức tồn GS25 không để Odoo tự tạo đơn mua,
    # vì đề xuất phải được quản lý cửa hàng xác nhận.
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get(
                "gs25_is_replenishment",
                self.env.context.get("default_gs25_is_replenishment"),
            ):
                self._gs25_check_level_access()
                vals["trigger"] = "manual"

        return super().create(vals_list)

    def _gs25_level_fields(self):
        return {
            "gs25_is_replenishment", "gs25_pack_qty", "gs25_note",
            "product_min_qty", "product_max_qty", "product_id",
            "location_id", "warehouse_id", "trigger", "active",
        }

    def write(self, vals):
        gs25_records = self.filtered("gs25_is_replenishment")

        if (
            (gs25_records or vals.get("gs25_is_replenishment"))
            and self._gs25_level_fields().intersection(vals)
        ):
            self._gs25_check_level_access()

        if vals.get("gs25_is_replenishment") or (
            gs25_records and vals.get("trigger") == "auto"
        ):
            vals = dict(vals, trigger="manual")

        result = super().write(vals)

        if vals.get("gs25_is_replenishment"):
            super(GS25StockWarehouseOrderpoint, self).write({"trigger": "manual"})

        return result

    def _gs25_check_level_access(self):
        if self.env.su:
            return

        if not self.env.user.has_group(
            "gs25_replenishment.group_gs25_replenishment_manager"
        ):
            raise AccessError(
                "Chỉ quản lý cửa hàng mới được thiết lập mức tồn kho GS25."
            )

    # 4. MỞ DANH SÁCH MỨC TỒN TỐI THIỂU CỦA CỬA HÀNG
    @api.model
    def action_gs25_open_min_levels(self):
        warehouse = self.env.company._gs25_check_replenishment_config()

        return {
            "type": "ir.actions.act_window",
            "name": "Mức tồn kho tối thiểu",
            "res_model": "stock.warehouse.orderpoint",
            "view_mode": "list",
            "views": [(
                self.env.ref(
                    "gs25_replenishment.view_gs25_orderpoint_list"
                ).id,
                "list",
            )],
            "search_view_id": self.env.ref(
                "gs25_replenishment.view_gs25_orderpoint_search"
            ).id,
            "domain": [
                ("gs25_is_replenishment", "=", True),
                ("company_id", "=", self.env.company.id),
            ],
            "context": {
                "default_gs25_is_replenishment": True,
                "default_trigger": "manual",
                "default_warehouse_id": warehouse.id,
                "default_location_id": warehouse.lot_stock_id.id,
            },
        }

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError

class GS25DateCheckRecord(models.Model):
    _name = "gs25.date.check.record"
    _description = "Phiếu kiểm tra hạn sử dụng GS25"
    _order = "check_date desc, id desc"

   
    # 1. THÔNG TIN PHIẾU KIỂM TRA
    name = fields.Char(
        string="Mã phiếu",
        default="Phiếu mới",
        required=True,
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
        required=True,
        default="good",
    )

    proposed_action = fields.Selection(
        [
            ("priority_sale", "Ưu tiên bán"),
            ("monitor", "Tiếp tục theo dõi"),
            ("remove", "Đề xuất loại bỏ"),
        ],
        string="Đề xuất xử lý",
        required=True,
        default="monitor",
    )

    state = fields.Selection(
        [
            ("draft", "Nháp"),
            ("waiting", "Chờ quản lý xác nhận"),
            ("approved", "Đã xác nhận"),
        ],
        string="Trạng thái",
        default="draft",
        required=True,
        copy=False,
    )

    note = fields.Text(
        string="Ghi chú",
    )


    # 3. KIỂM TRA DỮ LIỆU
    @api.constrains("checked_quantity")
    def _check_quantity(self):
        for record in self:
            if record.checked_quantity <= 0:
                raise ValidationError(
                    "Số lượng kiểm tra phải lớn hơn 0."
                )

   
    # 4. KIỂM SOÁT TẠO PHIẾU
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("state", "draft") != "draft":
                raise AccessError(
                    "Phiếu mới phải ở trạng thái Nháp."
                )

            vals["state"] = "draft"

        return super().create(vals_list)

   
    # 5. GỬI PHIẾU CHO QUẢN LÝ
    def action_submit(self):
        for record in self:
            if record.state != "draft":
                raise ValidationError(
                    "Chỉ có thể gửi phiếu đang ở trạng thái Nháp."
                )

        # Chuyển trạng thái bằng phương thức nội bộ
        self._gs25_update_state("waiting")
        return True

    
    # 6. QUẢN LÝ XÁC NHẬN PHIẾU
    def action_approve(self):
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

        self._gs25_update_state("approved")
        return True

    
    # 7. CHUYỂN TRẠNG THÁI NỘI BỘ
    def _gs25_update_state(self, new_state):
        """
        Chỉ sử dụng trong các phương thức
        chuyển trạng thái đã kiểm tra điều kiện.
        """
        if new_state not in ("waiting", "approved"):
            raise ValidationError(
                "Trạng thái chuyển đổi không hợp lệ."
            )

        # Gọi trực tiếp phương thức write của lớp cha
        # để không đi qua write() tùy chỉnh bên dưới.
        return super(GS25DateCheckRecord, self).write({
            "state": new_state,
        })


    # 8. KHÓA CHỈNH SỬA PHIẾU
    def write(self, vals):
        # Không cho đổi trạng thái bằng write thông thường
        if "state" in vals:
            raise AccessError(
                "Không được thay đổi trạng thái trực tiếp. "
                "Hãy sử dụng nút xử lý trên phiếu."
            )

        for record in self:
            if record.state == "waiting":
                raise AccessError(
                    "Phiếu đã gửi quản lý, "
                    "không được chỉnh sửa nội dung."
                )

            if record.state == "approved":
                raise AccessError(
                    "Phiếu đã xác nhận, "
                    "không được chỉnh sửa."
                )

        return super().write(vals)


    # 9. KHÔNG CHO XÓA PHIẾU ĐÃ GỬI
    def unlink(self):
        for record in self:
            if record.state != "draft":
                raise AccessError(
                    "Chỉ được xóa phiếu ở trạng thái Nháp."
                )

        return super().unlink()

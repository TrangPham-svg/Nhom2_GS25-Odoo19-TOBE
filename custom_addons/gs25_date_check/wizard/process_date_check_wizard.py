from odoo import fields, models
from odoo.exceptions import AccessError, ValidationError

class GS25DateCheckProcessWizard(models.TransientModel):
    _name = "gs25.date.check.process.wizard"
    _description = "Thực hiện xử lý hàng hóa GS25"


    # 1. THÔNG TIN PHIẾU KIỂM TRA
    record_id = fields.Many2one(
        "gs25.date.check.record",
        string="Phiếu kiểm tra",
        required=True,
        readonly=True,
    )

    lot_id = fields.Many2one(
        "stock.lot",
        related="record_id.lot_id",
        string="Số lô",
        readonly=True,
    )

    product_id = fields.Many2one(
        "product.product",
        related="record_id.product_id",
        string="Sản phẩm",
        readonly=True,
    )

    expiration_date = fields.Datetime(
        related="record_id.expiration_date",
        string="Ngày hết hạn",
        readonly=True,
    )

    # 2. THÔNG TIN PHƯƠNG ÁN XỬ LÝ
    quality_result = fields.Selection(
        related="record_id.quality_result",
        string="Kết quả kiểm tra",
        readonly=True,
    )

    proposed_action = fields.Selection(
        related="record_id.proposed_action",
        string="Phương án đã xác nhận",
        readonly=True,
    )

    checked_quantity = fields.Float(
        related="record_id.checked_quantity",
        string="Số lượng xử lý",
        readonly=True,
    )

    nvt_quantity = fields.Float(
        related="lot_id.gs25_nvt_quantity",
        string="Tồn kho hiện tại",
        readonly=True,
    )

    
    # 3. THÔNG TIN THỰC HIỆN XỬ LÝ
    next_check_date = fields.Datetime(
        string="Thời điểm kiểm tra lại",
    )

    processing_note = fields.Text(
        string="Ghi chú xử lý",
    )


    # 4. XÁC NHẬN THỰC HIỆN PHƯƠNG ÁN
    def action_confirm_process(self):
        self.ensure_one()

        manager_group = (
            "gs25_date_check.group_gs25_date_check_manager"
        )

        if not self.env.user.has_group(manager_group):
            raise AccessError(
                "Chỉ quản lý GS25 Date Check "
                "mới được thực hiện xử lý hàng hóa."
            )

        record = self.record_id

        if not record.exists():
            raise ValidationError(
                "Không tìm thấy phiếu kiểm tra."
            )

        if record.state != "approved":
            raise ValidationError(
                "Chỉ được thực hiện xử lý "
                "đối với phiếu đã xác nhận."
            )

        note = (self.processing_note or "").strip()

        next_check_date = False

        # PHƯƠNG ÁN 1: ƯU TIÊN BÁN

        if record.proposed_action == "priority_sale":

            if record.quality_result != "good":
                raise ValidationError(
                    "Chỉ được ưu tiên bán "
                    "hàng hóa đạt yêu cầu."
                )

            if (
                not record.expiration_date
                or record.expiration_date <= fields.Datetime.now()
            ):
                raise ValidationError(
                    "Không được ưu tiên bán "
                    "hàng hết hạn hoặc chưa có hạn sử dụng."
                )

        # PHƯƠNG ÁN 2: TIẾP TỤC THEO DÕI

        elif record.proposed_action == "monitor":

            if not self.next_check_date:
                raise ValidationError(
                    "Vui lòng chọn thời điểm kiểm tra lại."
                )

            if self.next_check_date <= fields.Datetime.now():
                raise ValidationError(
                    "Thời điểm kiểm tra lại "
                    "phải lớn hơn thời điểm hiện tại."
                )

            next_check_date = self.next_check_date

        # PHƯƠNG ÁN 3: LOẠI BỎ HÀNG HÓA

        elif record.proposed_action == "remove":

            if not note:
                raise ValidationError(
                    "Vui lòng nhập ghi chú "
                    "xác nhận việc loại bỏ hàng hóa."
                )

        else:
            raise ValidationError(
                "Phương án xử lý không hợp lệ."
            )

        # Gọi phương thức xử lý nghiệp vụ trong model chính
        # Model chính kiểm tra lại quyền, trạng thái và tồn kho.

        record._gs25_process(
            note=note,
            next_check_date=next_check_date,
        )

        return {
            "type": "ir.actions.act_window_close",
        }

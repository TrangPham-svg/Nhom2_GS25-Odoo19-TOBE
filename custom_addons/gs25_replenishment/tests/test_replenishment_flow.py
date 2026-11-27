import base64
from datetime import timedelta

from pytz import timezone

from odoo import fields
from odoo.exceptions import AccessError, ValidationError
from odoo.tests import Form, tagged
from odoo.tests.common import TransactionCase

from odoo.tests.common import new_test_user as mail_new_test_user


# A12. KIỂM THỬ TOÀN BỘ QUY TRÌNH ĐẶT HÀNG BỔ SUNG
@tagged("post_install", "-at_install", "gs25_replenishment")
class TestGS25Replenishment(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True))
        cls.company = cls.env.company

        # 1. Kho cửa hàng NVT và kho tổng mô phỏng
        cls.warehouse = cls.env["stock.warehouse"].search([
            ("code", "=", "NVT"),
            ("company_id", "=", cls.company.id),
        ], limit=1) or cls.env["stock.warehouse"].create({
            "name": "GS25 Nguyễn Văn Trỗi",
            "code": "NVT",
            "company_id": cls.company.id,
        })
        cls.location = cls.warehouse.lot_stock_id
        cls.company.write({
            "gs25_store_warehouse_id": cls.warehouse.id,
            "gs25_sales_history_days": 7,
            "gs25_lead_days": 1,
            "gs25_coverage_days": 2,
        })
        cls.central_partner = cls.company._gs25_get_central_partner()

        # 2. Người dùng: nhân viên, quản lý, kho tổng
        cls.staff = mail_new_test_user(
            cls.env, login="gs25_staff", name="Nhân viên GS25",
            groups="gs25_replenishment.group_gs25_replenishment_user",
            tz="Asia/Ho_Chi_Minh",
        )
        cls.manager = mail_new_test_user(
            cls.env, login="gs25_manager", name="Cửa hàng trưởng GS25",
            groups="gs25_replenishment.group_gs25_replenishment_manager",
            tz="Asia/Ho_Chi_Minh",
        )
        cls.central = mail_new_test_user(
            cls.env, login="gs25_central", name="Kho tổng GS25",
            groups="gs25_replenishment.group_gs25_replenishment_central",
            tz="Asia/Ho_Chi_Minh",
        )

        # 3. Sản phẩm quản lý tồn kho
        cls.product_7up = cls.env["product.product"].create({
            "name": "7UP 390ml",
            "default_code": "GS25-7UP",
            "barcode": "8934588012228",
            "type": "consu",
            "is_storable": True,
            "standard_price": 8000,
        })
        cls.product_sw = cls.env["product.product"].create({
            "name": "Sandwich trứng",
            "default_code": "GS25-SW",
            "type": "consu",
            "is_storable": True,
            "tracking": "lot",
        })
        cls.product_snack = cls.env["product.product"].create({
            "name": "Snack khoai tây",
            "default_code": "GS25-SNACK",
            "type": "consu",
            "is_storable": True,
        })
        cls.lot_sw = cls.env["stock.lot"].create({
            "name": "GS25-SW-001",
            "product_id": cls.product_sw.id,
            "company_id": cls.company.id,
        })

        Quant = cls.env["stock.quant"]
        Quant._update_available_quantity(cls.product_7up, cls.location, 30)
        Quant._update_available_quantity(
            cls.product_sw, cls.location, 10, lot_id=cls.lot_sw,
        )
        Quant._update_available_quantity(cls.product_snack, cls.location, 50)

        # 4. A04. Mức tồn tối thiểu do quản lý thiết lập
        Orderpoint = cls.env["stock.warehouse.orderpoint"].with_user(cls.manager)
        cls.op_7up = Orderpoint.create({
            "gs25_is_replenishment": True,
            "product_id": cls.product_7up.id,
            "warehouse_id": cls.warehouse.id,
            "location_id": cls.location.id,
            "product_min_qty": 20,
            "product_max_qty": 40,
            "gs25_pack_qty": 6,
        })
        cls.op_sw = Orderpoint.create({
            "gs25_is_replenishment": True,
            "product_id": cls.product_sw.id,
            "warehouse_id": cls.warehouse.id,
            "location_id": cls.location.id,
            "product_min_qty": 8,
            "product_max_qty": 15,
            "gs25_pack_qty": 1,
        })
        cls.op_snack = Orderpoint.create({
            "gs25_is_replenishment": True,
            "product_id": cls.product_snack.id,
            "warehouse_id": cls.warehouse.id,
            "location_id": cls.location.id,
            "product_min_qty": 10,
            "product_max_qty": 30,
        })

    # HÀM HỖ TRỢ
    def _local_time(self, days_ago=1):
        tz = timezone("Asia/Ho_Chi_Minh")
        value = fields.Datetime.now() - timedelta(days=days_ago)
        return value.replace(tzinfo=timezone("UTC")).astimezone(tz).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    def _make_csv(self, rows):
        content = "receipt_ref,line_no,sale_datetime,product_code,quantity\n"
        content += "\n".join(",".join(str(value) for value in row) for row in rows)
        return base64.b64encode(content.encode("utf-8"))

    def _import(self, rows, user=None, file_name="pos.csv"):
        user = user or self.staff
        record = self.env["gs25.pos.sale.import"].with_user(user).create({
            "file_data": self._make_csv(rows),
            "file_name": file_name,
        })
        record.action_check_data()
        return record

    def _qty(self, product):
        return product.with_context(location=self.location.id).qty_available

    def _generate(self, user=None):
        return self.env["gs25.replenishment.proposal"].with_user(
            user or self.staff
        )._gs25_generate_proposal()

    # 1. A01. CẤU HÌNH
    def test_01_config(self):
        self.assertEqual(self.company._gs25_get_store_warehouse(), self.warehouse)
        self.assertEqual(self.company._gs25_get_store_location(), self.location)
        self.assertTrue(self.central_partner)
        self.assertIn("✅", self.company.gs25_config_warning)

        with self.assertRaises(ValidationError):
            self.company.gs25_sales_history_days = 0

    # 2. A02-A03. IMPORT BÁN HÀNG VÀ CẬP NHẬT TỒN KHO
    def test_02_import_and_update_stock(self):
        day = self._local_time()
        record = self._import([
            ("HD0001", 1, day, "GS25-7UP", 2),
            ("HD0001", 2, day, "8934588012228", 3),   # tìm theo mã vạch
            ("HD0002", 1, day, "GS25-SW", 4),
        ])

        self.assertEqual(record.state, "checked")
        self.assertEqual(record.valid_count, 3)
        self.assertEqual(record.total_quantity, 9)

        record.action_process_stock()

        self.assertEqual(record.state, "done")
        self.assertEqual(record.picking_id.state, "done")
        self.assertEqual(record.picking_id.location_id, self.location)
        self.assertEqual(self._qty(self.product_7up), 25)
        self.assertEqual(self._qty(self.product_sw), 6)
        self.assertTrue(all(line.is_processed for line in record.line_ids))

    def test_03_prevent_duplicate_sales(self):
        day = self._local_time()
        rows = [("HD0100", 1, day, "GS25-7UP", 1)]
        first = self._import(rows)
        first.action_process_stock()

        # Cùng một file không được import lại
        with self.assertRaises(ValidationError):
            self._import(rows)

        # File khác nhưng chứa dòng đã ghi nhận và dòng trùng trong file
        second = self._import([
            ("HD0100", 1, day, "GS25-7UP", 1),
            ("HD0101", 1, day, "GS25-7UP", 2),
            ("HD0101", 1, day, "GS25-7UP", 2),
        ], file_name="pos2.csv")

        self.assertEqual(second.duplicate_count, 2)
        self.assertEqual(second.valid_count, 1)

        second.action_process_stock()
        self.assertEqual(self._qty(self.product_7up), 27)

        # Không ghi nhận lại phiếu đã hoàn tất
        with self.assertRaises(ValidationError):
            second.action_process_stock()

    def test_04_invalid_sales_rows(self):
        future = (
            fields.Datetime.now() + timedelta(days=3)
        ).strftime("%Y-%m-%d %H:%M:%S")
        record = self._import([
            ("HD0200", 1, self._local_time(), "KHONG-CO", 1),
            ("HD0200", 2, self._local_time(), "GS25-7UP", "abc"),
            ("HD0200", 3, self._local_time(), "GS25-7UP", -1),
            ("HD0200", 4, future, "GS25-7UP", 1),
            ("", 5, self._local_time(), "GS25-7UP", 1),
        ])

        self.assertEqual(record.error_count, 5)

        with self.assertRaises(ValidationError):
            record.action_process_stock()

        # Thiếu cột bắt buộc
        bad = self.env["gs25.pos.sale.import"].with_user(self.staff).create({
            "file_data": base64.b64encode(b"receipt_ref,quantity\nHD1,1"),
            "file_name": "bad.csv",
        })
        with self.assertRaises(ValidationError):
            bad.action_check_data()

    def test_05_insufficient_stock(self):
        record = self._import([
            ("HD0300", 1, self._local_time(), "GS25-SW", 50),
        ])

        with self.assertRaises(ValidationError):
            record.action_process_stock()

        self.assertEqual(self._qty(self.product_sw), 10)

    def test_06_import_protection(self):
        record = self._import([
            ("HD0400", 1, self._local_time(), "GS25-7UP", 1),
        ])

        with self.assertRaises(AccessError):
            record.write({"state": "done"})

        with self.assertRaises(AccessError):
            record.line_ids[0].write({"quantity": 100})

        record.action_process_stock()

        with self.assertRaises(AccessError):
            record.unlink()

    # 3. A04. MỨC TỒN TỐI THIỂU
    def test_07_min_level(self):
        # Luôn ở chế độ thủ công để Odoo không tự tạo đơn mua
        self.assertEqual(self.op_7up.trigger, "manual")
        self.op_7up.with_user(self.manager).write({"trigger": "auto"})
        self.assertEqual(self.op_7up.trigger, "manual")

        with self.assertRaises(AccessError):
            self.op_7up.with_user(self.staff).write({"product_min_qty": 5})

        with self.assertRaises(ValidationError):
            self.op_7up.with_user(self.manager).write({"gs25_pack_qty": 0})

        with self.assertRaises(ValidationError):
            self.op_7up.with_user(self.manager).write({
                "product_min_qty": 50,
                "product_max_qty": 10,
            })

        action = self.env["stock.warehouse.orderpoint"].with_user(
            self.manager
        ).action_gs25_open_min_levels()
        self.assertEqual(
            action["context"]["default_location_id"], self.location.id,
        )

    # 4. A06. CÔNG THỨC ĐỀ XUẤT
    def test_08_suggested_qty_formula(self):
        Proposal = self.env["gs25.replenishment.proposal"]

        # Không có dữ liệu bán: đặt lên mức tối đa, làm tròn theo thùng 6
        self.assertEqual(
            Proposal._gs25_compute_suggested_qty(15, 20, 40, 0, 1, 2, 6, 1), 30,
        )
        # Bán 10/ngày, 3 ngày: mục tiêu = max(40, 20 + 30) = 50
        self.assertEqual(
            Proposal._gs25_compute_suggested_qty(15, 20, 40, 10, 1, 2, 6, 1), 36,
        )
        # Tồn dự báo đã đủ
        self.assertEqual(
            Proposal._gs25_compute_suggested_qty(45, 20, 40, 0, 1, 2, 6, 1), 0,
        )

    # 5. A05-A11. TOÀN BỘ QUY TRÌNH
    def test_09_full_replenishment_flow(self):
        # Bán hàng làm 7UP và Sandwich xuống dưới mức tối thiểu
        record = self._import([
            ("HD0500", 1, self._local_time(1), "GS25-7UP", 8),
            ("HD0501", 1, self._local_time(2), "GS25-7UP", 6),
            ("HD0502", 1, self._local_time(1), "GS25-SW", 3),
        ])
        record.action_process_stock()
        self.assertEqual(self._qty(self.product_7up), 16)
        self.assertEqual(self._qty(self.product_sw), 7)

        # A05-A07. Nhân viên kiểm tra tồn và lập đề xuất
        proposal = self._generate()
        self.assertTrue(proposal)
        self.assertEqual(proposal.state, "draft")
        self.assertEqual(
            set(proposal.line_ids.product_id.ids),
            {self.product_7up.id, self.product_sw.id},
        )

        line_7up = proposal.line_ids.filtered(
            lambda line: line.product_id == self.product_7up
        )
        # Bán TB = 14/7 = 2/ngày; mục tiêu = max(40, 20 + 2*3) = 40
        # Cần 40 - 16 = 24, làm tròn theo thùng 6 = 24
        self.assertAlmostEqual(line_7up.avg_daily_sales, 2.0)
        self.assertEqual(line_7up.forecast_qty, 16)
        self.assertEqual(line_7up.suggested_qty, 24)

        # Sản phẩm đang có đề xuất chưa xử lý không bị đề xuất lặp
        self.assertFalse(self._generate())

        # Nhân viên không được duyệt hoặc đổi trạng thái
        with self.assertRaises(AccessError):
            proposal.with_user(self.staff).write({"state": "approved"})

        proposal.with_user(self.staff).action_submit()
        self.assertEqual(proposal.state, "waiting")

        with self.assertRaises(AccessError):
            proposal.with_user(self.staff).action_approve()

        with self.assertRaises(AccessError):
            line_7up.with_user(self.staff).write({"approved_qty": 12})

        # A08. Quản lý điều chỉnh số lượng: bắt buộc nhập lý do
        line_7up.with_user(self.manager).write({"approved_qty": 30})
        self.assertTrue(line_7up.is_adjusted)

        with self.assertRaises(ValidationError):
            proposal.with_user(self.manager).action_approve()

        line_7up.with_user(self.manager).write({
            "adjust_reason": "Sắp có chương trình khuyến mãi",
        })

        # A09. Quản lý duyệt
        proposal.with_user(self.manager).action_approve()
        self.assertEqual(proposal.state, "approved")
        self.assertEqual(proposal.approved_by_id, self.manager)

        with self.assertRaises(AccessError):
            line_7up.with_user(self.manager).write({"approved_qty": 6})

        # A10. Tạo đơn đặt hàng điện tử gửi kho tổng
        proposal.with_user(self.manager).action_create_purchase_order()
        purchase = proposal.purchase_id
        self.assertEqual(proposal.state, "ordered")
        self.assertEqual(purchase.partner_id, self.central_partner)
        self.assertEqual(purchase.picking_type_id, self.warehouse.in_type_id)
        self.assertEqual(purchase.gs25_dw_state, "not_sent")
        po_line_7up = purchase.order_line.filtered(
            lambda line: line.product_id == self.product_7up
        )
        self.assertEqual(po_line_7up.product_qty, 30)

        with self.assertRaises(ValidationError):
            proposal.with_user(self.manager).action_create_purchase_order()

        # A11. Gửi đơn: đơn được xác nhận và tạo phiếu nhập dự kiến tại NVT
        with self.assertRaises(AccessError):
            purchase.with_user(self.staff).action_gs25_send_to_central()

        purchase.with_user(self.manager).action_gs25_send_to_central()
        self.assertEqual(purchase.state, "purchase")
        self.assertEqual(purchase.gs25_dw_state, "sent")
        self.assertTrue(purchase.picking_ids)
        self.assertEqual(
            purchase.picking_ids.location_dest_id, self.location,
        )

        # Không sửa số lượng sau khi đã gửi
        with self.assertRaises(AccessError):
            po_line_7up.with_user(self.manager).write({"product_qty": 1})

        # Kho tổng mô phỏng: tiếp nhận -> xác nhận -> giao hàng
        with self.assertRaises(AccessError):
            purchase.with_user(self.manager).action_gs25_dw_receive()

        purchase.with_user(self.central).action_gs25_dw_receive()
        purchase.with_user(self.central).action_gs25_dw_confirm()
        purchase.with_user(self.central).action_gs25_dw_ship()

        self.assertEqual(purchase.gs25_dw_state, "shipping")
        self.assertEqual(proposal.dw_state, "shipping")
        self.assertEqual(
            purchase.gs25_dw_log_ids.mapped("state"),
            ["shipping", "confirmed", "received", "sent"],
        )

        with self.assertRaises(ValidationError):
            purchase.with_user(self.central).action_gs25_dw_receive()

        # Hàng sắp nhập đã tính vào tồn dự báo, không đề xuất lại
        self.assertFalse(self._generate())

    def test_10_reject_proposal(self):
        self.env["stock.quant"]._update_available_quantity(
            self.product_snack, self.location, -45,
        )
        proposal = self._generate()
        proposal.with_user(self.staff).action_submit()

        wizard = self.env["gs25.replenishment.reject.wizard"].with_user(
            self.manager
        ).create({
            "proposal_id": proposal.id,
            "reject_reason": "Tạm ngưng bán sản phẩm",
        })
        wizard.action_confirm_reject()

        self.assertEqual(proposal.state, "rejected")
        self.assertEqual(proposal.rejected_by_id, self.manager)

        with self.assertRaises(ValidationError):
            proposal.with_user(self.manager).action_approve()

        # Sau khi từ chối, lần kiểm tra sau được đề xuất lại
        self.assertTrue(self._generate())

    def _ordered_purchase(self):
        self.env["stock.quant"]._update_available_quantity(
            self.product_snack, self.location, -45,
        )
        proposal = self._generate()
        proposal.with_user(self.staff).action_submit()
        proposal.with_user(self.manager).action_approve()
        proposal.with_user(self.manager).action_create_purchase_order()
        purchase = proposal.purchase_id
        purchase.with_user(self.manager).action_gs25_send_to_central()
        purchase.with_user(self.central).action_gs25_dw_receive()
        return proposal, purchase

    def test_11_central_partial(self):
        proposal, purchase = self._ordered_purchase()
        line = purchase.order_line
        self.assertEqual(line.product_qty, 25)

        action = purchase.with_user(self.central).with_context(
            gs25_response_mode="partial",
        ).action_gs25_open_dw_response_wizard()
        wizard_form = Form(
            self.env[action["res_model"]].with_user(self.central).with_context(
                action["context"],
            )
        )
        with wizard_form.line_ids.edit(0) as wizard_line:
            wizard_line.available_qty = 10
        wizard_form.note = "Kho tổng còn 10 gói"
        wizard_form.save().action_confirm()

        self.assertEqual(purchase.gs25_dw_state, "partial")
        self.assertEqual(line.product_qty, 10)
        move = purchase.picking_ids.move_ids.filtered(
            lambda m: m.state not in ("done", "cancel")
        )
        self.assertEqual(sum(move.mapped("product_uom_qty")), 10)
        # Không phát sinh phiếu trả hàng cho phần kho tổng không giao
        self.assertFalse(purchase.picking_ids.filtered(
            lambda p: p.location_dest_id.usage == "supplier"
            or p.picking_type_id.code == "outgoing"
        ))

        purchase.with_user(self.central).action_gs25_dw_ship()
        self.assertEqual(purchase.gs25_dw_state, "shipping")

    def test_12_central_reject(self):
        proposal, purchase = self._ordered_purchase()

        wizard = self.env["gs25.dw.response.wizard"].with_user(self.central).create({
            "purchase_id": purchase.id,
            "mode": "reject",
            "note": "Kho tổng hết hàng",
        })
        wizard.action_confirm()

        self.assertEqual(purchase.gs25_dw_state, "rejected")
        self.assertEqual(purchase.state, "cancel")
        self.assertTrue(all(p.state == "cancel" for p in purchase.picking_ids))

        # Đơn bị từ chối: sản phẩm được đề xuất lại ở lần kiểm tra sau
        self.assertTrue(self._generate())

    def test_13_cron_generate(self):
        self.env["stock.quant"]._update_available_quantity(
            self.product_snack, self.location, -45,
        )
        self.env["gs25.replenishment.proposal"]._gs25_cron_generate_proposals()
        proposal = self.env["gs25.replenishment.proposal"].search([
            ("source", "=", "cron"),
        ])
        self.assertEqual(len(proposal), 1)
        self.assertEqual(proposal.line_ids.product_id, self.product_snack)

        # Người dùng không tự tạo phiếu đề xuất thủ công
        with self.assertRaises(AccessError):
            self.env["gs25.replenishment.proposal"].with_user(self.staff).create({
                "warehouse_id": self.warehouse.id,
            })

    def test_14_refresh_and_remove_line(self):
        record = self._import([
            ("HD0600", 1, self._local_time(1), "GS25-7UP", 15),
        ])
        record.action_process_stock()
        self.env["stock.quant"]._update_available_quantity(
            self.product_snack, self.location, -45,
        )
        proposal = self._generate()
        self.assertEqual(len(proposal.line_ids), 2)

        # Nhân viên bỏ sản phẩm không cần đặt khỏi phiếu Nháp
        snack_line = proposal.line_ids.filtered(
            lambda line: line.product_id == self.product_snack
        )
        proposal.with_user(self.staff).write({
            "line_ids": [(2, snack_line.id)],
        })
        self.assertEqual(len(proposal.line_ids), 1)

        # Tồn 7UP được bổ sung đủ: cập nhật số liệu sẽ bỏ dòng 7UP
        self.env["stock.quant"]._update_available_quantity(
            self.product_7up, self.location, 30,
        )
        proposal.with_user(self.staff).action_refresh_lines()
        self.assertFalse(proposal.line_ids)

        with self.assertRaises(ValidationError):
            proposal.with_user(self.staff).action_submit()

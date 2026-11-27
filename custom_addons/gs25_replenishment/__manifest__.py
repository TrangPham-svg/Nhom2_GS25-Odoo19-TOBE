{
    'name': 'GS25 - Replenishment Management',
    'summary': 'Quan ly dat hang bo sung tai GS25',
    'description': """
        GS25 Replenishment Management
        - Cau hinh Inventory va Purchase cho dat hang bo sung
        - Import du lieu ban hang tu POS (file CSV)
        - Cap nhat ton kho tu du lieu ban hang, chong ghi nhan trung
        - Thiet lap muc ton kho toi thieu/toi da theo san pham
        - Kiem tra ton kho va phat hien san pham can bo sung
        - Tu dong de xuat so luong can dat theo ton du bao va suc ban
        - Tong hop danh sach de xuat dat hang
        - Quan ly kiem tra, dieu chinh so luong
        - Xac nhan hoac tu choi de xuat
        - Tao don dat hang dien tu gui kho tong
        - Ghi nhan trang thai xu ly phia kho tong (mo phong)
        - Tu dong kiem tra ton kho hang ngay
    """,
    'author': 'Nhom 2',
    'category': 'Inventory',
    'version': '19.0.2.0.0',
    'depends': ['stock', 'purchase_stock', 'mail'],
    'data': [
    'security/security.xml',
    'security/ir.model.access.csv',
    'data/ir_sequence_data.xml',
    'data/res_partner_data.xml',
    'data/ir_cron_data.xml',
    'views/views.xml',
    'views/pos_sale_import_views.xml',
    'views/stock_orderpoint_views.xml',
    'views/replenishment_proposal_views.xml',
    'views/purchase_order_views.xml',
    'wizard/reject_proposal_wizard_views.xml',
    'wizard/dw_response_wizard_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}

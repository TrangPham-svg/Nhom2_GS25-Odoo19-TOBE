{
    'name': 'GS25 - Expiration Date Check',
    'summary': 'Kiem tra va xu ly hang can han su dung',
    'description': """
        GS25 Expiration Date Check
        - Theo doi ma lo va han su dung
        - Tu dong phat hien hang can han
        - Ho tro kiem tra va xu ly hang het han
        - Quan ly phieu kiem tra va phe duyet
        - Yeu cau bo sung thong tin va huy phieu
        - Danh dau hang hoa can uu tien ban
        - Thiet lap lich kiem tra lai
        - Loai bo hang hoa va cap nhat ton kho
        - Luu lich su thuc hien xu ly
        - Tu dong sinh ma phieu kiem tra
        - Kiem soat trung ma phieu kiem tra
        - Tu dong thong bao ket qua xu ly cho nhan vien
        - Tu dong nhac lich kiem tra lai hang hoa
    """,
    'author': 'Nhom 2',
    'category': 'Inventory',
    'version': '19.0.7.0.0',
    'depends': ['stock', 'product_expiry', 'mail'],
    'data': [
    'security/security.xml',
    'security/ir.model.access.csv',
    'data/ir_sequence_data.xml',
    'data/ir_cron_data.xml',
    'views/views.xml',
    'views/date_check_record_views.xml',
    'wizard/cancel_date_check_wizard_views.xml',
    'wizard/process_date_check_wizard_views.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
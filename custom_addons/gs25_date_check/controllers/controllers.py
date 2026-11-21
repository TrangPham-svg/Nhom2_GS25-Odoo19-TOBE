# from odoo import http


# class Gs25DateCheck(http.Controller):
#     @http.route('/gs25_date_check/gs25_date_check', auth='public')
#     def index(self, **kw):
#         return "Hello, world"

#     @http.route('/gs25_date_check/gs25_date_check/objects', auth='public')
#     def list(self, **kw):
#         return http.request.render('gs25_date_check.listing', {
#             'root': '/gs25_date_check/gs25_date_check',
#             'objects': http.request.env['gs25_date_check.gs25_date_check'].search([]),
#         })

#     @http.route('/gs25_date_check/gs25_date_check/objects/<model("gs25_date_check.gs25_date_check"):obj>', auth='public')
#     def object(self, obj, **kw):
#         return http.request.render('gs25_date_check.object', {
#             'object': obj
#         })


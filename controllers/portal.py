# -*- coding: utf-8 -*-
from datetime import datetime, date, timedelta
from werkzeug.exceptions import Forbidden, NotFound
from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.osv import expression


class AttendanceOtCustomerPortal(CustomerPortal):

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        user = request.env.user
        employee = self._get_current_employee()

        if employee:
            Sheet = request.env['attendance.ot.approval.sheet'].sudo()
            values['attendance_ot_count'] = Sheet.search_count([('employee_id', '=', employee.id)])

            # Subordinate check
            subordinates = request.env['hr.employee'].sudo().search([
                '|', '|', '|',
                ('parent_id', '=', employee.id),
                ('leave_manager_id', '=', user.id),
                ('time_off_officer_id', '=', user.id),
                ('department_id.manager_id', '=', employee.id)
            ])
            values['is_attendance_ot_manager'] = bool(subordinates)
            if subordinates:
                Sheet._ensure_subordinate_sheets(subordinates)
                values['attendance_ot_to_approve_count'] = Sheet.search_count([
                    ('employee_id', 'in', subordinates.ids),
                    ('state', '=', 'submitted'),
                ])
            else:
                values['attendance_ot_to_approve_count'] = 0
        else:
            values['attendance_ot_count'] = 0
            values['attendance_ot_to_approve_count'] = 0
            values['is_attendance_ot_manager'] = False

        return values

    def _get_current_employee(self):
        user = request.env.user
        if hasattr(user, 'get_portal_employee'):
            emp = user.get_portal_employee()
            if emp:
                return emp
        emp = getattr(user, 'employee_id', False) or (user.employee_ids[0] if hasattr(user, 'employee_ids') and user.employee_ids else False)
        if not emp:
            emp = request.env['hr.employee'].sudo().search([('user_id', '=', user.id)], limit=1)
        return emp

    def _check_sheet_access(self, sheet_id, mode='read'):
        sheet = request.env['attendance.ot.approval.sheet'].sudo().browse(sheet_id)
        if not sheet.exists():
            raise NotFound()

        user = request.env.user
        employee = self._get_current_employee()

        is_owner = employee and sheet.employee_id.id == employee.id
        is_manager = employee and (
            getattr(employee, 'is_portal_attendance_manager', False) or
            sheet.employee_id.parent_id.id == employee.id or
            sheet.employee_id.leave_manager_id.id == user.id or
            sheet.manager_id.id == employee.id or
            sheet.manager_id.user_id.id == user.id
        )
        is_officer = user.has_group('hr.group_hr_user') or user.has_group('base.group_system')

        if mode == 'read':
            if not (is_owner or is_manager or is_officer):
                raise Forbidden(_("You do not have access to view this attendance OT sheet."))
        elif mode == 'approve':
            if not (is_manager or is_officer):
                raise Forbidden(_("You do not have permission to approve or reject this sheet."))

        return sheet

    # -------------------------------------------------------------------------
    # My Attendance OT Sheets
    # -------------------------------------------------------------------------

    @http.route(['/my/attendance_ot', '/my/attendance_ot/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_attendance_ot(self, page=1, sortby=None, filterby=None, **kw):
        employee = self._get_current_employee()
        if not employee:
            return request.render('time_off_portal_exposure.portal_no_employee_linked', {
                'page_name': 'attendance_ot_no_employee'
            })

        Sheet = request.env['attendance.ot.approval.sheet'].sudo()

        sortings = {
            'date_desc': {'label': _('Date (Newest)'), 'order': 'date_from desc, id desc'},
            'date_asc': {'label': _('Date (Oldest)'), 'order': 'date_from asc, id asc'},
            'state': {'label': _('Status'), 'order': 'state asc'},
        }
        if not sortby or sortby not in sortings:
            sortby = 'date_desc'
        order = sortings[sortby]['order']

        filters = {
            'all': {'label': _('All Sheets'), 'domain': []},
            'submitted': {'label': _('Pending Approval'), 'domain': [('state', '=', 'submitted')]},
            'approved': {'label': _('Approved'), 'domain': [('state', '=', 'approved')]},
            'rejected': {'label': _('Rejected'), 'domain': [('state', '=', 'rejected')]},
        }
        if not filterby or filterby not in filters:
            filterby = 'all'

        base_domain = [('employee_id', '=', employee.id)]
        domain = expression.AND([base_domain, filters[filterby]['domain']])

        total_sheets = Sheet.search_count(domain)
        pager = portal_pager(
            url="/my/attendance_ot",
            url_args={'sortby': sortby, 'filterby': filterby},
            total=total_sheets,
            page=page,
            step=10
        )

        sheets = Sheet.search(domain, order=order, limit=10, offset=pager['offset'])

        # Subordinates check
        subordinates = request.env['hr.employee'].sudo().search([
            '|', ('parent_id', '=', employee.id), ('leave_manager_id', '=', request.env.uid)
        ])
        is_manager = bool(subordinates)

        values = {
            'page_name': 'attendance_ot_dashboard',
            'employee': employee,
            'sheets': sheets,
            'pager': pager,
            'sortby': sortby,
            'sortings': sortings,
            'filterby': filterby,
            'filters': filters,
            'default_url': '/my/attendance_ot',
            'is_manager': is_manager,
        }
        return request.render('attendance_ot_portal_approval.portal_my_attendance_ot_dashboard', values)

    # -------------------------------------------------------------------------
    # Portal Manager Approvals Dashboard
    # -------------------------------------------------------------------------

    @http.route(['/my/attendance_ot/to_approve', '/my/attendance_ot/to_approve/page/<int:page>'], type='http', auth='user', website=True)
    def portal_my_attendance_ot_to_approve(self, page=1, filterby=None, sortby=None, employee_id=None, date_from=None, date_to=None, **kw):
        employee = self._get_current_employee()
        if not employee:
            return request.render('time_off_portal_exposure.portal_no_employee_linked', {
                'page_name': 'attendance_ot_no_employee'
            })

        subordinates = request.env['hr.employee'].sudo().search([
            '|', '|', '|',
            ('parent_id', '=', employee.id),
            ('leave_manager_id', '=', request.env.uid),
            ('time_off_officer_id', '=', request.env.uid),
            ('department_id.manager_id', '=', employee.id)
        ])
        if not subordinates:
            return request.render('time_off_portal_exposure.portal_not_a_manager', {
                'page_name': 'attendance_ot_not_manager'
            })

        Sheet = request.env['attendance.ot.approval.sheet'].sudo()

        # Parse date range parameters or fallback to default payroll cycle
        def_date_from, def_date_to = Sheet._get_default_payroll_period()
        date_from_str = date_from or kw.get('date_from') or request.params.get('date_from')
        date_to_str = date_to or kw.get('date_to') or request.params.get('date_to')

        if date_from_str:
            try:
                selected_date_from = fields.Date.from_string(date_from_str)
            except Exception:
                selected_date_from = def_date_from
        else:
            selected_date_from = def_date_from

        if date_to_str:
            try:
                selected_date_to = fields.Date.from_string(date_to_str)
            except Exception:
                selected_date_to = def_date_to
        else:
            selected_date_to = def_date_to

        # Automatically ensure all subordinates with attendance/OT records have sheets in submitted state for this range
        Sheet._ensure_subordinate_sheets(subordinates, date_from=selected_date_from, date_to=selected_date_to)

        # Build Subordinate Employees Statistics strictly for the selected date range
        subordinate_stats = []
        for sub in subordinates:
            sub_sheets = Sheet.search([
                ('employee_id', '=', sub.id),
                ('date_from', '<=', selected_date_to),
                ('date_to', '>=', selected_date_from),
            ])
            pending_sheets = sub_sheets.filtered(lambda s: s.state == 'submitted')
            pending_cnt = len(pending_sheets)
            approved_ot = sum(sub_sheets.mapped('total_approved_ot_hours'))
            raw_ot = sum(sub_sheets.mapped('total_raw_ot_hours'))
            unapproved_late = sum(sub_sheets.mapped('total_approved_late_hours'))

            # Check attendance records directly for this date range if raw_ot is 0
            if not sub_sheets or raw_ot == 0.0:
                rec_ot = sum(request.env['zkteco.attendance.record'].sudo().search([
                    ('employee_id', '=', sub.id),
                    ('date', '>=', selected_date_from),
                    ('date', '<=', selected_date_to),
                ]).mapped('overtime_hours'))
                raw_ot = max(raw_ot, rec_ot)

            subordinate_stats.append({
                'id': sub.id,
                'name': sub.name,
                'code': getattr(sub, 'fms_employee_id', False) or sub.name[:3].upper(),
                'job': sub.job_title or (sub.job_id.name if sub.job_id else 'Employee'),
                'department': sub.department_id.name if sub.department_id else 'General',
                'pending_count': pending_cnt,
                'total_sheets': len(sub_sheets),
                'raw_ot': raw_ot,
                'approved_ot': approved_ot,
                'unapproved_late': unapproved_late,
            })

        sortings = {
            'date_desc': {'label': _('Date (Newest)'), 'order': 'date_from desc, id desc'},
            'date_asc': {'label': _('Date (Oldest)'), 'order': 'date_from asc, id asc'},
            'employee': {'label': _('Employee Name'), 'order': 'employee_id asc'},
        }
        if not sortby or sortby not in sortings:
            sortby = 'date_desc'
        order = sortings[sortby]['order']

        filters = {
            'pending': {'label': _('Pending My Approval'), 'domain': [('state', '=', 'submitted')]},
            'all': {'label': _('All Team Sheets'), 'domain': []},
            'approved': {'label': _('Approved'), 'domain': [('state', '=', 'approved')]},
            'rejected': {'label': _('Rejected'), 'domain': [('state', '=', 'rejected')]},
        }
        if not filterby or filterby not in filters:
            filterby = 'pending'

        selected_employee_id = int(employee_id) if employee_id and str(employee_id).isdigit() else None
        if selected_employee_id and selected_employee_id in subordinates.ids:
            base_domain = [('employee_id', '=', selected_employee_id)]
        else:
            base_domain = [('employee_id', 'in', subordinates.ids)]
            selected_employee_id = None

        date_domain = [
            ('date_from', '<=', selected_date_to),
            ('date_to', '>=', selected_date_from),
        ]
        domain = expression.AND([base_domain, filters[filterby]['domain'], date_domain])

        total_sheets = Sheet.search_count(domain)
        url_args = {
            'sortby': sortby,
            'filterby': filterby,
            'date_from': selected_date_from.strftime('%Y-%m-%d'),
            'date_to': selected_date_to.strftime('%Y-%m-%d'),
        }
        if selected_employee_id:
            url_args['employee_id'] = selected_employee_id

        pager = portal_pager(
            url="/my/attendance_ot/to_approve",
            url_args=url_args,
            total=total_sheets,
            page=page,
            step=10
        )

        sheets = Sheet.search(domain, order=order, limit=10, offset=pager['offset'])

        pending_approval_count = Sheet.search_count([
            ('employee_id', 'in', subordinates.ids),
            ('state', '=', 'submitted'),
            ('date_from', '<=', selected_date_to),
            ('date_to', '>=', selected_date_from),
        ])

        # Date preset options
        today = fields.Date.today()
        cycle_from, cycle_to = Sheet._get_default_payroll_period(today)
        cal_month_from = today.replace(day=1)
        if today.month == 12:
            cal_month_to = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            cal_month_to = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        prev_month_end = cal_month_from - timedelta(days=1)
        prev_month_from = prev_month_end.replace(day=1)

        values = {
            'page_name': 'attendance_ot_to_approve',
            'employee': employee,
            'subordinates': subordinates,
            'subordinate_stats': subordinate_stats,
            'selected_employee_id': selected_employee_id,
            'sheets': sheets,
            'pending_approval_count': pending_approval_count,
            'pager': pager,
            'sortby': sortby,
            'sortings': sortings,
            'filterby': filterby,
            'filters': filters,
            'date_from': selected_date_from.strftime('%Y-%m-%d'),
            'date_to': selected_date_to.strftime('%Y-%m-%d'),
            'presets': {
                'cycle_from': cycle_from.strftime('%Y-%m-%d'),
                'cycle_to': cycle_to.strftime('%Y-%m-%d'),
                'cal_month_from': cal_month_from.strftime('%Y-%m-%d'),
                'cal_month_to': cal_month_to.strftime('%Y-%m-%d'),
                'prev_month_from': prev_month_from.strftime('%Y-%m-%d'),
                'prev_month_to': prev_month_end.strftime('%Y-%m-%d'),
            },
            'default_url': '/my/attendance_ot/to_approve',
        }
        return request.render('attendance_ot_portal_approval.portal_my_attendance_ot_to_approve', values)

    # -------------------------------------------------------------------------
    # Single Sheet View & Interactive Manager Approval Page
    # -------------------------------------------------------------------------

    @http.route(['/my/attendance_ot/<int:sheet_id>'], type='http', auth='user', website=True)
    def portal_my_attendance_ot_detail(self, sheet_id, approved=None, rejected=None, updated=None, reopened=None, **kw):
        sheet = self._check_sheet_access(sheet_id, mode='read')
        employee = self._get_current_employee()

        is_owner = employee and sheet.employee_id.id == employee.id
        is_manager = employee and (
            sheet.employee_id.parent_id.id == employee.id or
            sheet.employee_id.leave_manager_id.id == request.env.uid or
            sheet.manager_id.id == employee.id or
            sheet.manager_id.user_id.id == request.env.uid
        )
        is_officer = request.env.user.has_group('hr.group_hr_user') or request.env.user.has_group('base.group_system')

        values = {
            'page_name': 'attendance_ot_detail',
            'sheet': sheet,
            'employee': employee,
            'is_owner': is_owner,
            'is_manager': is_manager or is_officer,
            'is_officer': is_officer,
            'approved': bool(approved),
            'rejected': bool(rejected),
            'updated': bool(updated),
            'reopened': bool(reopened),
            'object': sheet,
        }
        return request.render('attendance_ot_portal_approval.portal_my_attendance_ot_detail', values)

    # -------------------------------------------------------------------------
    # Manager Line Adjustments & Approval Actions
    # -------------------------------------------------------------------------

    @http.route(['/my/attendance_ot/<int:sheet_id>/update_lines'], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def portal_my_attendance_ot_update_lines(self, sheet_id, **post):
        sheet = self._check_sheet_access(sheet_id, mode='approve')

        for line in sheet.line_ids:
            line_prefix = f"line_{line.id}_"
            is_ot_acceptable = post.get(f"{line_prefix}is_ot_acceptable") == 'on'
            ot_category = post.get(f"{line_prefix}ot_category", line.ot_category or 'day')
            approved_ot_str = post.get(f"{line_prefix}approved_ot_hours")
            
            absent_action = post.get(f"{line_prefix}absent_action")
            is_absent_excused_cb = post.get(f"{line_prefix}is_absent_excused") == 'on'
            if absent_action == 'excuse':
                is_absent_excused = True
            elif absent_action == 'deduct':
                is_absent_excused = False
            else:
                is_absent_excused = is_absent_excused_cb

            approved_late_str = post.get(f"{line_prefix}approved_late_hours")
            notes = post.get(f"{line_prefix}notes", "").strip()

            line_vals = {
                'is_ot_acceptable': is_ot_acceptable,
                'ot_category': ot_category,
                'is_absent_excused': is_absent_excused,
                'notes': notes,
            }

            # Calculate Approved OT Hours per category
            if approved_ot_str is not None and approved_ot_str != '':
                try:
                    ot_h = max(float(approved_ot_str), 0.0)
                except ValueError:
                    ot_h = 0.0
            else:
                ot_h = line.raw_ot_hours if is_ot_acceptable else 0.0

            if not is_ot_acceptable:
                ot_h = 0.0

            line_vals.update({
                'approved_ot_day_hours': ot_h if ot_category == 'day' else 0.0,
                'approved_ot_night_hours': ot_h if ot_category == 'night' else 0.0,
                'approved_ot_weekend_hours': ot_h if ot_category == 'weekend' else 0.0,
                'approved_ot_holiday_hours': ot_h if ot_category == 'holiday' else 0.0,
                'approved_ot_hours': ot_h,
            })

            # Calculate Absent / Late Deduction Hours
            if is_absent_excused:
                late_h = 0.0
            elif approved_late_str is not None and approved_late_str != '':
                try:
                    late_h = max(float(approved_late_str), 0.0)
                except ValueError:
                    late_h = line.raw_late_hours
            else:
                late_h = line.raw_late_hours

            line_vals['approved_late_hours'] = late_h

            line.write(line_vals)

        return request.redirect(f'/my/attendance_ot/{sheet_id}?updated=1')

    @http.route(['/my/attendance_ot/<int:sheet_id>/approve'], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def portal_my_attendance_ot_approve(self, sheet_id, redirect_to=None, **post):
        sheet = self._check_sheet_access(sheet_id, mode='approve')
        # First save any line changes submitted in form
        self.portal_my_attendance_ot_update_lines(sheet_id, **post)
        sheet.action_approve()

        if redirect_to == 'to_approve':
            return request.redirect('/my/attendance_ot/to_approve?approved=1')
        return request.redirect(f'/my/attendance_ot/{sheet_id}?approved=1')

    @http.route(['/my/attendance_ot/<int:sheet_id>/reject'], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def portal_my_attendance_ot_reject(self, sheet_id, rejection_reason=None, redirect_to=None, **post):
        sheet = self._check_sheet_access(sheet_id, mode='approve')
        if rejection_reason:
            sheet.rejection_reason = rejection_reason.strip()
        sheet.action_reject()

        if redirect_to == 'to_approve':
            return request.redirect('/my/attendance_ot/to_approve?rejected=1')
        return request.redirect(f'/my/attendance_ot/{sheet_id}?rejected=1')

    @http.route(['/my/attendance_ot/<int:sheet_id>/reopen'], type='http', auth='user', methods=['POST', 'GET'], website=True, csrf=True)
    def portal_my_attendance_ot_reopen(self, sheet_id, redirect_to=None, **kw):
        sheet = self._check_sheet_access(sheet_id, mode='approve')
        sheet.action_reopen()

        if redirect_to == 'to_approve':
            return request.redirect('/my/attendance_ot/to_approve?reopened=1')
        return request.redirect(f'/my/attendance_ot/{sheet_id}?reopened=1')

    @http.route(['/my/attendance_ot/<int:sheet_id>/update_period'], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def portal_my_attendance_ot_update_period(self, sheet_id, date_from=None, date_to=None, **post):
        sheet = self._check_sheet_access(sheet_id, mode='approve')
        if sheet.state in ('draft', 'submitted') and date_from and date_to:
            try:
                d_from = fields.Date.from_string(date_from)
                d_to = fields.Date.from_string(date_to)
                if d_from and d_to and d_from <= d_to:
                    sheet.write({
                        'date_from': d_from,
                        'date_to': d_to,
                        'period_type': 'custom',
                    })
                    sheet.action_fetch_attendance_records()
            except Exception:
                pass
        return request.redirect(f'/my/attendance_ot/{sheet_id}?period_updated=1')

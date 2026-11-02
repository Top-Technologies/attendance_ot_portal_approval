# -*- coding: utf-8 -*-
from datetime import datetime, date, timedelta
from werkzeug.exceptions import Forbidden, NotFound
from odoo import http, fields, _
from odoo.http import request
from odoo.addons.portal.controllers.portal import CustomerPortal, pager as portal_pager
from odoo.osv import expression


class AttendanceOtCustomerPortal(CustomerPortal):

    def _is_attendance_hr_admin(self, user=None):
        """Check if user has HR Officer/Admin permissions to manage company-wide or unassigned attendance sheets."""
        if user is None:
            user = request.env.user
        return bool(
            request.env.is_superuser()
            or user.has_group('base.group_system')
            or user.has_group('attendance_ot_portal_approval.group_attendance_ot_manager')
            or user.has_group('hr.group_hr_manager')
            or user.has_group('zkteco_attendance.group_zkteco_admin')
        )

    def _get_manageable_subordinates(self, user, employee, scope='team'):
        """
        Return the hr.employee recordset of manageable subordinates for the current user.
        - HR / System Admins: Can oversee all employees or unassigned employees.
        - Regular Managers: STRICTLY subordinates in their recursive reporting hierarchy (full subtree).
          Unassigned employees (parent_id = False) and cross-team employees are NEVER returned.
          The manager themselves is excluded.
        """
        is_hr_admin = self._is_attendance_hr_admin(user)

        if is_hr_admin:
            if scope == 'unassigned':
                return request.env['hr.employee'].sudo().search([
                    ('active', '=', True),
                    ('parent_id', '=', False),
                ])
            elif scope == 'all':
                return request.env['hr.employee'].sudo().search([
                    ('active', '=', True),
                ])
            elif employee:
                # Direct & indirect subordinates of this HR user
                sub_ids = employee._get_subordinate_hierarchy_ids(include_self=False)
                if sub_ids:
                    return request.env['hr.employee'].sudo().browse(list(sub_ids)).filtered(lambda e: e.active)
                return request.env['hr.employee'].sudo().search([('active', '=', True)])
            else:
                return request.env['hr.employee'].sudo().search([('active', '=', True)])

        if not employee:
            return request.env['hr.employee']

        # Regular Manager: full recursive subtree, strictly assigned subordinates only
        sub_ids = employee._get_subordinate_hierarchy_ids(include_self=False)
        if not sub_ids:
            return request.env['hr.employee']

        subordinates = request.env['hr.employee'].sudo().browse(list(sub_ids)).filtered(
            lambda e: e.active and bool(e.parent_id) and e.id != employee.id
        )
        return subordinates

    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        user = request.env.user
        employee = self._get_current_employee()
        Sheet = request.env['attendance.ot.approval.sheet'].sudo()

        if employee:
            values['attendance_ot_count'] = Sheet.search_count([('employee_id', '=', employee.id)])
        else:
            values['attendance_ot_count'] = 0

        is_hr_admin = self._is_attendance_hr_admin(user)
        subordinates = self._get_manageable_subordinates(user, employee, scope='team' if not is_hr_admin else 'all')
        is_manager = bool(subordinates) or is_hr_admin
        values['is_attendance_ot_manager'] = is_manager

        if is_manager and subordinates:
            Sheet._ensure_subordinate_sheets(subordinates)
            values['attendance_ot_to_approve_count'] = Sheet.search_count([
                ('employee_id', 'in', subordinates.ids),
                ('state', '=', 'submitted'),
            ])
        elif is_hr_admin:
            values['attendance_ot_to_approve_count'] = Sheet.search_count([
                ('state', '=', 'submitted'),
            ])
        else:
            values['attendance_ot_to_approve_count'] = 0

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
        is_hr_admin = self._is_attendance_hr_admin(user)

        is_owner = employee and sheet.employee_id.id == employee.id

        # Disallow self-approval / self-rejection strictly
        if mode == 'approve' and is_owner:
            raise Forbidden(_("You cannot approve, reject, or adjust your own attendance OT sheet. Approvals must come from your manager."))

        # Unassigned employee sheets (no manager): Only HR / Admins can read or approve
        if not sheet.employee_id.parent_id:
            if not is_hr_admin:
                raise Forbidden(_("Unassigned employee sheets can only be reviewed or approved by HR or System Administrators."))
            return sheet

        # Assigned employee sheets:
        if is_hr_admin:
            return sheet

        # Regular manager check: Employee must be strictly in manager's reporting line
        if not employee or not employee.is_in_subordinate_hierarchy(sheet.employee_id):
            raise Forbidden(_("Access Denied: You do not have permission to view or approve attendance sheets outside your reporting line."))

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
    def portal_my_attendance_ot_to_approve(self, page=1, filterby=None, sortby=None, employee_id=None, date_from=None, date_to=None, scope='team', **kw):
        user = request.env.user
        employee = self._get_current_employee()
        is_hr_admin = self._is_attendance_hr_admin(user)

        if not employee and not is_hr_admin:
            return request.render('time_off_portal_exposure.portal_no_employee_linked', {
                'page_name': 'attendance_ot_no_employee'
            })

        # Scope enforcement: Regular managers are strictly restricted to 'team' (their own reporting subtree)
        if not is_hr_admin:
            scope = 'team'

        subordinates = self._get_manageable_subordinates(user, employee, scope=scope)
        if not subordinates and not is_hr_admin:
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

        # Automatically ensure sheets exist in submitted state for subordinates in this range
        if subordinates:
            Sheet._ensure_subordinate_sheets(subordinates, date_from=selected_date_from, date_to=selected_date_to)

        sub_ids = subordinates.ids if subordinates else []

        # ---------------------------------------------------------------------
        # FAST BATCH AGGREGATION: Single DB queries instead of N+1 loops
        # ---------------------------------------------------------------------
        if sub_ids:
            all_sub_sheets = Sheet.search([
                ('employee_id', 'in', sub_ids),
                ('date_from', '<=', selected_date_to),
                ('date_to', '>=', selected_date_from),
            ])
            all_att_records = request.env['zkteco.attendance.record'].sudo().search([
                ('employee_id', 'in', sub_ids),
                ('date', '>=', selected_date_from),
                ('date', '<=', selected_date_to),
            ])
        else:
            all_sub_sheets = Sheet.browse()
            all_att_records = request.env['zkteco.attendance.record'].sudo().browse()

        # Group sheets and attendance records by employee_id for O(1) in-memory lookups
        sheets_by_emp = {}
        for s in all_sub_sheets:
            sheets_by_emp.setdefault(s.employee_id.id, []).append(s)

        att_by_emp = {}
        for rec in all_att_records:
            att_by_emp.setdefault(rec.employee_id.id, []).append(rec)

        # Team Summary Metrics scoped strictly to viewer's manageable team
        present_emp_ids = {r.employee_id.id for r in all_att_records if r.status == 'present'}
        absent_emp_ids = {r.employee_id.id for r in all_att_records if r.status == 'absent'}
        late_emp_ids = {r.employee_id.id for r in all_att_records if r.is_late}
        on_leave_emp_ids = {r.employee_id.id for r in all_att_records if r.status == 'on_leave'}

        pending_approval_count = len([s for s in all_sub_sheets if s.state == 'submitted'])

        team_metrics = {
            'total_team': len(subordinates),
            'present_count': len(present_emp_ids),
            'absent_count': len(absent_emp_ids),
            'late_count': len(late_emp_ids),
            'on_leave_count': len(on_leave_emp_ids),
            'pending_count': pending_approval_count,
            'total_raw_ot': sum(all_sub_sheets.mapped('total_raw_ot_hours')),
            'total_approved_ot': sum(all_sub_sheets.mapped('total_approved_ot_hours')),
            'total_deduction_hours': sum(all_sub_sheets.mapped('total_approved_late_hours')),
        }

        # Build Subordinate Statistics in memory
        subordinate_stats = []
        for sub in subordinates:
            emp_sheets = sheets_by_emp.get(sub.id, [])
            pending_cnt = len([s for s in emp_sheets if s.state == 'submitted'])
            approved_ot = sum(s.total_approved_ot_hours for s in emp_sheets)
            raw_ot = sum(s.total_raw_ot_hours for s in emp_sheets)
            unapproved_late = sum(s.total_approved_late_hours for s in emp_sheets)

            if raw_ot == 0.0 and sub.id in att_by_emp:
                raw_ot = sum(r.overtime_hours or 0.0 for r in att_by_emp[sub.id])

            subordinate_stats.append({
                'id': sub.id,
                'name': sub.name,
                'code': getattr(sub, 'fms_employee_id', False) or sub.name[:3].upper(),
                'job': sub.job_title or (sub.job_id.name if sub.job_id else 'Employee'),
                'department': sub.department_id.name if sub.department_id else 'General',
                'parent_name': sub.parent_id.name if sub.parent_id else _('Unassigned'),
                'pending_count': pending_cnt,
                'total_sheets': len(emp_sheets),
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
        if selected_employee_id and selected_employee_id in sub_ids:
            base_domain = [('employee_id', '=', selected_employee_id)]
        else:
            base_domain = [('employee_id', 'in', sub_ids)]
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
            'scope': scope,
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
            'is_hr_admin': is_hr_admin,
            'scope': scope,
            'subordinates': subordinates,
            'subordinate_stats': subordinate_stats,
            'selected_employee_id': selected_employee_id,
            'sheets': sheets,
            'team_metrics': team_metrics,
            'pending_approval_count': pending_approval_count,
            'pager': pager,
            'sortby': sortby,
            'sortings': sortings,
            'filterby': filterby,
            'filters': filters,
            'date_from': selected_date_from.strftime('%Y-%m-%d'),
            'date_to': selected_date_to.strftime('%Y-%m-%d'),
            'presets': {
                'today': today.strftime('%Y-%m-%d'),
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

    @http.route(['/my/attendance_ot/<int:sheet_id>/quick_approve'], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def portal_my_attendance_ot_quick_approve(self, sheet_id, **post):
        sheet = self._check_sheet_access(sheet_id, mode='approve')
        sheet.action_approve()
        redirect_url = post.get('redirect_url') or '/my/attendance_ot/to_approve?approved=1'
        return request.redirect(redirect_url)

    @http.route(['/my/attendance_ot/<int:sheet_id>/quick_reject'], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def portal_my_attendance_ot_quick_reject(self, sheet_id, rejection_reason=None, **post):
        sheet = self._check_sheet_access(sheet_id, mode='approve')
        if rejection_reason:
            sheet.rejection_reason = rejection_reason.strip()
        sheet.action_reject()
        redirect_url = post.get('redirect_url') or '/my/attendance_ot/to_approve?rejected=1'
        return request.redirect(redirect_url)

    @http.route(['/my/attendance_ot/batch_approve'], type='http', auth='user', methods=['POST'], website=True, csrf=True)
    def portal_my_attendance_ot_batch_approve(self, date_from=None, date_to=None, employee_id=None, scope='team', **post):
        user = request.env.user
        employee = self._get_current_employee()
        is_hr_admin = self._is_attendance_hr_admin(user)
        if not is_hr_admin:
            scope = 'team'

        subordinates = self._get_manageable_subordinates(user, employee, scope=scope)
        if not subordinates and not is_hr_admin:
            return request.redirect('/my/attendance_ot/to_approve')

        Sheet = request.env['attendance.ot.approval.sheet'].sudo()
        domain = [('state', '=', 'submitted')]
        if subordinates:
            domain.append(('employee_id', 'in', subordinates.ids))
        if date_from:
            try:
                d_from = fields.Date.from_string(date_from)
                domain.append(('date_to', '>=', d_from))
            except Exception:
                pass
        if date_to:
            try:
                d_to = fields.Date.from_string(date_to)
                domain.append(('date_from', '<=', d_to))
            except Exception:
                pass
        if employee_id and str(employee_id).isdigit():
            emp_id = int(employee_id)
            if emp_id in subordinates.ids:
                domain.append(('employee_id', '=', emp_id))

        sheets_to_approve = Sheet.search(domain)
        count = 0
        for sheet in sheets_to_approve:
            try:
                self._check_sheet_access(sheet.id, mode='approve')
                sheet.action_approve()
                count += 1
            except Exception:
                continue

        return request.redirect(f'/my/attendance_ot/to_approve?batch_approved={count}')

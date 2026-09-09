# -*- coding: utf-8 -*-
from datetime import datetime, date, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class AttendanceOtApprovalSheet(models.Model):
    _name = 'attendance.ot.approval.sheet'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Attendance OT & Absent Approval Sheet'
    _order = 'date_from desc, id desc'

    name = fields.Char(
        string='Sheet Reference',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    employee_id = fields.Many2one(
        'hr.employee',
        string='Employee',
        required=True,
        ondelete='cascade',
        index=True,
        tracking=True,
    )
    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        related='employee_id.department_id',
        store=True,
    )
    job_id = fields.Many2one(
        'hr.job',
        string='Job Position',
        related='employee_id.job_id',
        store=True,
    )
    manager_id = fields.Many2one(
        'hr.employee',
        string='Manager',
        compute='_compute_manager_id',
        store=True,
        readonly=False,
        help='Manager responsible for reviewing and approving this attendance report.',
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    date_from = fields.Date(
        string='From Date',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
        tracking=True,
    )
    date_to = fields.Date(
        string='To Date',
        required=True,
        default=lambda self: fields.Date.today(),
        tracking=True,
    )
    period_type = fields.Selection([
        ('payroll_cycle', 'Payroll Cycle'),
        ('custom', 'Custom Period'),
        ('monthly', 'Monthly'),
        ('weekly', 'Weekly'),
        ('daily', 'Daily'),
    ], string='Period Type', default='payroll_cycle', required=True)

    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ], string='Status', default='submitted', required=True, tracking=True, index=True)

    line_ids = fields.One2many(
        'attendance.ot.approval.line',
        'sheet_id',
        string='Daily Attendance Lines',
        copy=True,
    )
    contract_id = fields.Many2one(
        'hr.contract',
        string='Active Contract',
        compute='_compute_contract_id',
        store=True,
        help='The active contract updated upon sheet approval.',
    )

    # Computed Raw Totals
    total_worked_hours = fields.Float(
        string='Total Worked Hours',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )
    total_expected_hours = fields.Float(
        string='Total Expected Hours',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )
    total_raw_ot_hours = fields.Float(
        string='Raw OT Hours',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
        help='Total Overtime hours recorded by attendance machine before manager approval.',
    )
    total_raw_late_hours = fields.Float(
        string='Raw Late/Absent Hours',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )
    total_absent_days = fields.Integer(
        string='Total Absent Days',
        compute='_compute_sheet_totals',
        store=True,
    )
    total_approved_absent_days = fields.Integer(
        string='Approved Deduction Absent Days',
        compute='_compute_sheet_totals',
        store=True,
        help='Unexcused absent days that count towards deduction.',
    )
    total_excused_absent_days = fields.Integer(
        string='Excused Absent Days',
        compute='_compute_sheet_totals',
        store=True,
        help='Absent days excused by manager.',
    )

    # Computed Approved Totals per OT Factor Category
    total_ot_day_hours = fields.Float(
        string='Approved Day OT (1.5x) Hrs',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )
    total_ot_night_hours = fields.Float(
        string='Approved Night OT (1.75x) Hrs',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )
    total_ot_weekend_hours = fields.Float(
        string='Approved Weekend OT (2.0x) Hrs',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )
    total_ot_holiday_hours = fields.Float(
        string='Approved Holiday OT (2.5x) Hrs',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )

    total_approved_ot_hours = fields.Float(
        string='Total Approved OT Hours',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
        help='Total approved overtime hours across all categories.',
    )
    total_approved_late_hours = fields.Float(
        string='Unapproved Late/Absent Hours (Deduction)',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
        help='Unapproved late or absent hours to be deducted from contract.',
    )
    total_excused_late_hours = fields.Float(
        string='Excused Late/Absent Hours',
        compute='_compute_sheet_totals',
        store=True,
        digits=(16, 2),
    )

    approved_by_id = fields.Many2one(
        'res.users',
        string='Approved By',
        readonly=True,
        copy=False,
    )
    approval_date = fields.Datetime(
        string='Approval Date',
        readonly=True,
        copy=False,
    )
    rejection_reason = fields.Text(
        string='Rejection Reason',
        tracking=True,
    )

    _sql_constraints = [
        ('employee_period_unique', 'unique(employee_id, date_from, date_to, period_type)',
         'An attendance approval sheet already exists for this employee in the specified period!')
    ]

    @api.depends('employee_id', 'employee_id.parent_id', 'employee_id.leave_manager_id')
    def _compute_manager_id(self):
        for sheet in self:
            if sheet.employee_id:
                leave_mgr_emp = sheet.employee_id.leave_manager_id.employee_id if sheet.employee_id.leave_manager_id else False
                sheet.manager_id = sheet.employee_id.parent_id or leave_mgr_emp or False
            else:
                sheet.manager_id = False

    @api.depends('employee_id', 'state')
    def _compute_contract_id(self):
        for sheet in self:
            if sheet.employee_id:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', sheet.employee_id.id),
                    ('state', 'in', ('open', 'draft')),
                ], order='date_start desc', limit=1)
                sheet.contract_id = contract.id if contract else False
            else:
                sheet.contract_id = False

    @api.depends(
        'line_ids',
        'line_ids.worked_hours',
        'line_ids.expected_hours',
        'line_ids.raw_ot_hours',
        'line_ids.raw_late_hours',
        'line_ids.approved_ot_day_hours',
        'line_ids.approved_ot_night_hours',
        'line_ids.approved_ot_weekend_hours',
        'line_ids.approved_ot_holiday_hours',
        'line_ids.approved_ot_hours',
        'line_ids.approved_late_hours',
        'line_ids.status',
        'line_ids.is_absent_excused',
    )
    def _compute_sheet_totals(self):
        for sheet in self:
            worked = sum(sheet.line_ids.mapped('worked_hours'))
            expected = sum(sheet.line_ids.mapped('expected_hours'))
            raw_ot = sum(sheet.line_ids.mapped('raw_ot_hours'))
            raw_late = sum(sheet.line_ids.mapped('raw_late_hours'))
            
            ot_day = sum(sheet.line_ids.mapped('approved_ot_day_hours'))
            ot_night = sum(sheet.line_ids.mapped('approved_ot_night_hours'))
            ot_weekend = sum(sheet.line_ids.mapped('approved_ot_weekend_hours'))
            ot_holiday = sum(sheet.line_ids.mapped('approved_ot_holiday_hours'))
            approved_ot = sum(sheet.line_ids.mapped('approved_ot_hours'))
            
            approved_late = sum(sheet.line_ids.mapped('approved_late_hours'))
            absent_lines = sheet.line_ids.filtered(lambda l: l.status == 'absent')
            absent_count = len(absent_lines)
            excused_absent_count = len(absent_lines.filtered(lambda l: l.is_absent_excused))
            deduction_absent_count = max(absent_count - excused_absent_count, 0)
            excused_late = sum(sheet.line_ids.filtered(lambda l: l.is_absent_excused).mapped('raw_late_hours'))

            sheet.total_worked_hours = worked
            sheet.total_expected_hours = expected
            sheet.total_raw_ot_hours = raw_ot
            sheet.total_raw_late_hours = raw_late

            sheet.total_ot_day_hours = ot_day
            sheet.total_ot_night_hours = ot_night
            sheet.total_ot_weekend_hours = ot_weekend
            sheet.total_ot_holiday_hours = ot_holiday
            sheet.total_approved_ot_hours = approved_ot

            sheet.total_approved_late_hours = approved_late
            sheet.total_absent_days = absent_count
            sheet.total_excused_absent_days = excused_absent_count
            sheet.total_approved_absent_days = deduction_absent_count
            sheet.total_excused_late_hours = excused_late

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                emp_id = vals.get('employee_id')
                emp = self.env['hr.employee'].browse(emp_id) if emp_id else False
                emp_code = emp.fms_employee_id or (emp.name[:3].upper() if emp and emp.name else 'EMP')
                d_from = vals.get('date_from') or fields.Date.today()
                d_to = vals.get('date_to') or fields.Date.today()
                d_from_str = d_from.strftime('%Y%m%d') if hasattr(d_from, 'strftime') else str(d_from).replace('-', '')
                d_to_str = d_to.strftime('%Y%m%d') if hasattr(d_to, 'strftime') else str(d_to).replace('-', '')
                if d_from_str[:6] == d_to_str[:6] and vals.get('period_type') == 'monthly':
                    vals['name'] = f"ATT-OT-{d_from_str[:6]}-{emp_code}"
                else:
                    vals['name'] = f"ATT-OT-{d_from_str}-{d_to_str}-{emp_code}"
            # Default state to 'submitted' directly so managers immediately receive approvals
            if 'state' not in vals:
                vals['state'] = 'submitted'
        sheets = super().create(vals_list)
        for sheet in sheets:
            if not sheet.line_ids:
                sheet.action_fetch_attendance_records()
        return sheets

    def action_fetch_attendance_records(self):
        """Fetch matching zkteco.attendance.record entries for the period and generate daily lines."""
        for sheet in self:
            if not sheet.employee_id or not sheet.date_from or not sheet.date_to:
                continue

            # In draft or submitted, remove any lines that fall outside the sheet's date range
            if sheet.state in ('draft', 'submitted'):
                out_of_range_lines = sheet.line_ids.filtered(
                    lambda l: l.date < sheet.date_from or l.date > sheet.date_to
                )
                if out_of_range_lines:
                    out_of_range_lines.unlink()

            # Search attendance records strictly within the sheet's date range
            att_records = self.env['zkteco.attendance.record'].search([
                ('employee_id', '=', sheet.employee_id.id),
                ('date', '>=', sheet.date_from),
                ('date', '<=', sheet.date_to),
            ], order='date asc')

            existing_lines_by_rec = {l.attendance_record_id.id: l for l in sheet.line_ids if l.attendance_record_id}
            existing_lines_by_date = {l.date: l for l in sheet.line_ids if not l.attendance_record_id and l.date}

            lines_vals = []
            for rec in att_records:
                existing_line = existing_lines_by_rec.get(rec.id) or existing_lines_by_date.get(rec.date)
                if existing_line:
                    # Sync updated metrics from machine record if needed
                    upd_vals = {}
                    if existing_line.worked_hours != rec.worked_hours:
                        upd_vals['worked_hours'] = rec.worked_hours
                    if existing_line.raw_ot_hours != (rec.overtime_hours or 0.0):
                        upd_vals['raw_ot_hours'] = rec.overtime_hours or 0.0
                        if existing_line.is_ot_acceptable:
                            cat = existing_line.ot_category or 'day'
                            upd_vals[f'approved_ot_{cat}_hours'] = rec.overtime_hours or 0.0
                            upd_vals['approved_ot_hours'] = rec.overtime_hours or 0.0
                    late_h = (rec.late_minutes or 0) / 60.0
                    if existing_line.raw_late_hours != late_h:
                        upd_vals['raw_late_hours'] = late_h
                        upd_vals['raw_late_minutes'] = rec.late_minutes or 0
                        if not existing_line.is_absent_excused:
                            upd_vals['approved_late_hours'] = late_h
                    if hasattr(rec, 'missed_punch_type') and existing_line.missed_punch_type != rec.missed_punch_type:
                        upd_vals['missed_punch_type'] = rec.missed_punch_type
                    if upd_vals:
                        existing_line.write(upd_vals)
                    continue

                raw_ot = rec.overtime_hours or 0.0
                late_mins = rec.late_minutes or 0
                late_hours = late_mins / 60.0

                # Auto-categorize OT type based on day of week / leave status
                is_weekend = rec.date.weekday() in (5, 6) if rec.date else False
                is_holiday = rec.status == 'on_leave'
                
                if is_holiday:
                    default_cat = 'holiday'
                elif is_weekend:
                    default_cat = 'weekend'
                else:
                    default_cat = 'day'

                day_h = raw_ot if default_cat == 'day' else 0.0
                night_h = raw_ot if default_cat == 'night' else 0.0
                weekend_h = raw_ot if default_cat == 'weekend' else 0.0
                holiday_h = raw_ot if default_cat == 'holiday' else 0.0

                lines_vals.append({
                    'sheet_id': sheet.id,
                    'attendance_record_id': rec.id,
                    'date': rec.date,
                    'status': rec.status,
                    'missed_punch_type': getattr(rec, 'missed_punch_type', False),
                    'first_checkin': rec.first_checkin,
                    'last_checkout': rec.last_checkout,
                    'worked_hours': rec.worked_hours,
                    'expected_hours': rec.expected_hours,
                    'raw_ot_hours': raw_ot,
                    'raw_late_minutes': late_mins,
                    'raw_late_hours': late_hours,
                    'is_ot_acceptable': True if raw_ot > 0 else False,
                    'ot_category': default_cat,
                    'approved_ot_day_hours': day_h,
                    'approved_ot_night_hours': night_h,
                    'approved_ot_weekend_hours': weekend_h,
                    'approved_ot_holiday_hours': holiday_h,
                    'is_absent_excused': False,
                    'approved_late_hours': late_hours if rec.status == 'absent' or late_hours > 0 else 0.0,
                })

            if lines_vals:
                self.env['attendance.ot.approval.line'].create(lines_vals)

    def _safe_message_post(self, body):
        try:
            self.sudo().message_post(body=body)
        except Exception:
            pass

    def action_submit(self):
        for sheet in self:
            if not sheet.line_ids:
                sheet.action_fetch_attendance_records()
            sheet.state = 'submitted'
            sheet._safe_message_post(_("Attendance OT & Absent sheet submitted for manager approval."))

    def action_approve(self):
        for sheet in self:
            sheet.state = 'approved'
            sheet.approved_by_id = self.env.uid
            sheet.approval_date = fields.Datetime.now()
            sheet._sync_to_contract()
            sheet._safe_message_post(_(
                "Attendance OT & Absent sheet APPROVED by %s.<br/>"
                "<strong>Approved OT Hours (Total):</strong> %.2f hrs "
                "(Day: %.2f | Night: %.2f | Weekend: %.2f | Holiday: %.2f)<br/>"
                "<strong>Approved Late/Absent Deduction Hours:</strong> %.2f hrs<br/>"
                "Active Contract updated successfully."
            ) % (
                self.env.user.name,
                sheet.total_approved_ot_hours,
                sheet.total_ot_day_hours,
                sheet.total_ot_night_hours,
                sheet.total_ot_weekend_hours,
                sheet.total_ot_holiday_hours,
                sheet.total_approved_late_hours
            ))

    def action_reject(self):
        for sheet in self:
            sheet.state = 'rejected'
            sheet._safe_message_post(_("Attendance OT & Absent sheet REJECTED by %s. Reason: %s") % (
                self.env.user.name, sheet.rejection_reason or _('No reason provided')
            ))

    def action_reset_draft(self):
        for sheet in self:
            sheet.state = 'draft'

    def action_reopen(self):
        """Reopen an approved or rejected sheet for manager adjustments."""
        for sheet in self:
            sheet.state = 'submitted'
            sheet._safe_message_post(_("Attendance OT & Absent sheet REOPENED for adjustments by %s.") % self.env.user.name)

    def action_sync_to_contract(self):
        """Manually push approved OT and absent hours to active contract."""
        for sheet in self:
            if sheet.state == 'approved':
                sheet._sync_to_contract()
                sheet._safe_message_post(_("Manually re-synced approved OT and Absent hours to Active Contract by %s.") % self.env.user.name)

    def _sync_to_contract(self):
        """Update active employee contract with approved multi-factor OT and Absent hours."""
        for sheet in self:
            contract = sheet.contract_id
            if not contract:
                contract = self.env['hr.contract'].sudo().search([
                    ('employee_id', '=', sheet.employee_id.id),
                    ('state', 'in', ('open', 'draft')),
                ], order='date_start desc', limit=1)

            if contract:
                sheet.sudo().contract_id = contract.id
                # Sync multi-factor OT break downs and absent deduction hours/days to contract
                contract.sudo().write({
                    'ot_day_hours': sheet.total_ot_day_hours,
                    'ot_night_hours': sheet.total_ot_night_hours,
                    'ot_weekend_hours': sheet.total_ot_weekend_hours,
                    'ot_holiday_hours': sheet.total_ot_holiday_hours,
                    'approved_absent_hours': sheet.total_approved_late_hours,
                    'approved_absent_days': sheet.total_approved_absent_days,
                })

    @api.model
    def _get_default_payroll_period(self, target_date=None):
        """
        Calculate default payroll cycle dates.
        Supports 9th of previous month to 10th of current month (e.g. 2026-08-09 to 2026-09-10).
        """
        if not target_date:
            target_date = fields.Date.today()
        elif isinstance(target_date, str):
            target_date = fields.Date.from_string(target_date)

        # Cutoff on the 10th:
        # If target day is <= 10 (e.g. Sep 7), current cycle is 9th of prev month to 10th of this month (e.g. Aug 9 to Sep 10).
        # If target day > 10 (e.g. Sep 15), next cycle is 9th of this month to 10th of next month (e.g. Sep 9 to Oct 10).
        if target_date.day <= 10:
            if target_date.month == 1:
                date_from = date(target_date.year - 1, 12, 9)
            else:
                date_from = date(target_date.year, target_date.month - 1, 9)
            date_to = date(target_date.year, target_date.month, 10)
        else:
            date_from = date(target_date.year, target_date.month, 9)
            if target_date.month == 12:
                date_to = date(target_date.year + 1, 1, 10)
            else:
                date_to = date(target_date.year, target_date.month + 1, 10)
        return date_from, date_to

    @api.model
    def _ensure_subordinate_sheets(self, subordinates=None, target_date=None, date_from=None, date_to=None, period_type=None):
        """
        Automatically ensure attendance approval sheets exist and are in 'submitted'
        (Pending Manager Approval) state for all subordinates who have attendance or OT records
        in the specified period (e.g. 2026-08-09 to 2026-09-10).
        """
        if date_from and isinstance(date_from, str):
            date_from = fields.Date.from_string(date_from)
        if date_to and isinstance(date_to, str):
            date_to = fields.Date.from_string(date_to)

        if not date_from or not date_to:
            def_from, def_to = self._get_default_payroll_period(target_date)
            date_from = date_from or def_from
            date_to = date_to or def_to

        if not period_type:
            if date_from.day == 1 and (date_to + timedelta(days=1)).day == 1 and date_from.month == date_to.month:
                period_type = 'monthly'
            else:
                period_type = 'payroll_cycle'

        if subordinates is None:
            subordinates = self.env['hr.employee'].search([('active', '=', True)])

        sheets_to_return = self.env['attendance.ot.approval.sheet']
        for emp in subordinates:
            # Check if this employee has any attendance records for this period
            att_count = self.env['zkteco.attendance.record'].search_count([
                ('employee_id', '=', emp.id),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ])
            if not att_count:
                continue

            sheet = self.search([
                ('employee_id', '=', emp.id),
                ('date_from', '=', date_from),
                ('date_to', '=', date_to),
            ], limit=1)

            if not sheet:
                sheet = self.create({
                    'employee_id': emp.id,
                    'date_from': date_from,
                    'date_to': date_to,
                    'period_type': period_type,
                    'state': 'submitted',
                })
            else:
                # If sheet exists in draft, auto-advance to submitted so manager sees it immediately
                if sheet.state == 'draft':
                    sheet.state = 'submitted'
                # Synchronize attendance records
                sheet.action_fetch_attendance_records()

            sheets_to_return |= sheet

        return sheets_to_return

    @api.model
    def generate_monthly_sheets(self, target_date=None, date_from=None, date_to=None):
        """Cron job / helper method to generate sheets for all active employees and submit directly to managers."""
        if date_from and isinstance(date_from, str):
            date_from = fields.Date.from_string(date_from)
        if date_to and isinstance(date_to, str):
            date_to = fields.Date.from_string(date_to)

        if not date_from or not date_to:
            date_from, date_to = self._get_default_payroll_period(target_date)

        employees = self.env['hr.employee'].search([('active', '=', True)])
        created_count = 0
        for emp in employees:
            att_count = self.env['zkteco.attendance.record'].search_count([
                ('employee_id', '=', emp.id),
                ('date', '>=', date_from),
                ('date', '<=', date_to),
            ])
            existing = self.search([
                ('employee_id', '=', emp.id),
                ('date_from', '=', date_from),
                ('date_to', '=', date_to),
            ], limit=1)
            if not existing:
                sheet = self.create({
                    'employee_id': emp.id,
                    'date_from': date_from,
                    'date_to': date_to,
                    'period_type': 'payroll_cycle',
                    'state': 'submitted' if att_count > 0 else 'draft',
                })
                created_count += 1
            else:
                if existing.state == 'draft' and att_count > 0:
                    existing.state = 'submitted'
                existing.action_fetch_attendance_records()
        return created_count


class AttendanceOtApprovalLine(models.Model):
    _name = 'attendance.ot.approval.line'
    _description = 'Daily Attendance OT & Absent Approval Line'
    _order = 'date asc, id asc'

    sheet_id = fields.Many2one(
        'attendance.ot.approval.sheet',
        string='Approval Sheet',
        required=True,
        ondelete='cascade',
        index=True,
    )
    employee_id = fields.Many2one(
        'hr.employee',
        related='sheet_id.employee_id',
        store=True,
        string='Employee',
    )
    attendance_record_id = fields.Many2one(
        'zkteco.attendance.record',
        string='Attendance Record',
        ondelete='set null',
    )
    date = fields.Date(
        string='Date',
        required=True,
    )
    day_name = fields.Char(
        string='Day of Week',
        compute='_compute_day_name',
        store=True,
    )
    status = fields.Selection([
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('missed_punch', 'Missed Punch'),
        ('on_leave', 'On Leave'),
    ], string='Attendance Status', default='present', required=True)
    missed_punch_type = fields.Selection([
        ('morning', 'Missed Morning Punch'),
        ('afternoon', 'Missed Afternoon Punch'),
    ], string='Missed Punch Detail')

    first_checkin = fields.Datetime(string='First Check-in')
    last_checkout = fields.Datetime(string='Last Check-out')

    worked_hours = fields.Float(string='Worked Hrs', digits=(16, 2))
    expected_hours = fields.Float(string='Expected Hrs', default=8.0, digits=(16, 2))

    # Raw Metrics from Machine
    raw_ot_hours = fields.Float(string='Raw OT Hrs', digits=(16, 2))
    raw_late_minutes = fields.Integer(string='Late Mins')
    raw_late_hours = fields.Float(string='Late/Absent Hrs', digits=(16, 2))

    # Manager Approval Selections per Category
    is_ot_acceptable = fields.Boolean(
        string='OT Acceptable',
        default=True,
        help='Check if the overtime worked on this day is acceptable for payment.',
    )
    ot_category = fields.Selection([
        ('day', 'Day Work (1.5x)'),
        ('night', 'Night Work (1.75x)'),
        ('weekend', 'Weekends Work (2.0x)'),
        ('holiday', 'Holiday Work (2.5x)'),
    ], string='OT Category', default='day', required=True)

    approved_ot_day_hours = fields.Float(string='Day OT (1.5x) Hrs', digits=(16, 2))
    approved_ot_night_hours = fields.Float(string='Night OT (1.75x) Hrs', digits=(16, 2))
    approved_ot_weekend_hours = fields.Float(string='Weekend OT (2.0x) Hrs', digits=(16, 2))
    approved_ot_holiday_hours = fields.Float(string='Holiday OT (2.5x) Hrs', digits=(16, 2))

    approved_ot_hours = fields.Float(
        string='Total Approved OT',
        compute='_compute_approved_ot_hours',
        store=True,
        readonly=False,
        digits=(16, 2),
        help='Approved overtime hours for payroll.',
    )
    is_absent_excused = fields.Boolean(
        string='Absence Excused',
        default=False,
        help='Check if the late arrival or absence on this day is excused by the manager.',
    )
    approved_late_hours = fields.Float(
        string='Deduction Hours',
        digits=(16, 2),
        help='Unapproved late/absent hours to be deducted from payroll contract.',
    )
    notes = fields.Char(string='Manager Notes')

    @api.depends('date')
    def _compute_day_name(self):
        for line in self:
            if line.date:
                line.day_name = line.date.strftime('%A')
            else:
                line.day_name = ''

    @api.depends(
        'approved_ot_day_hours',
        'approved_ot_night_hours',
        'approved_ot_weekend_hours',
        'approved_ot_holiday_hours',
    )
    def _compute_approved_ot_hours(self):
        for line in self:
            line.approved_ot_hours = (
                (line.approved_ot_day_hours or 0.0) +
                (line.approved_ot_night_hours or 0.0) +
                (line.approved_ot_weekend_hours or 0.0) +
                (line.approved_ot_holiday_hours or 0.0)
            )

    @api.onchange('ot_category', 'raw_ot_hours', 'is_ot_acceptable')
    def _onchange_ot_category_or_acceptance(self):
        for line in self:
            if not line.is_ot_acceptable:
                line.approved_ot_day_hours = 0.0
                line.approved_ot_night_hours = 0.0
                line.approved_ot_weekend_hours = 0.0
                line.approved_ot_holiday_hours = 0.0
            else:
                line.approved_ot_day_hours = line.raw_ot_hours if line.ot_category == 'day' else 0.0
                line.approved_ot_night_hours = line.raw_ot_hours if line.ot_category == 'night' else 0.0
                line.approved_ot_weekend_hours = line.raw_ot_hours if line.ot_category == 'weekend' else 0.0
                line.approved_ot_holiday_hours = line.raw_ot_hours if line.ot_category == 'holiday' else 0.0

    @api.onchange('is_absent_excused', 'raw_late_hours')
    def _onchange_is_absent_excused(self):
        for line in self:
            if line.is_absent_excused:
                line.approved_late_hours = 0.0
            else:
                line.approved_late_hours = line.raw_late_hours

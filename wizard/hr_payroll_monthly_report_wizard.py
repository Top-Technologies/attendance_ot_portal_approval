# -*- coding: utf-8 -*-

import io
import base64
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.tools.misc import xlsxwriter

from . import ethiopian_date_utils as eth_utils


class HrPayrollMonthlyReportWizard(models.TransientModel):
    _name = 'hr.payroll.monthly.report.wizard'
    _description = 'Monthly Payroll Reports (Overtime, Allowance, Absent, Deductions)'

    report_type = fields.Selection([
        ('overtime', 'Monthly Overtime Report (የትርፍ ሰዓት ሪፖርት)'),
        ('allowance', 'Monthly Allowance Report (የአበል ሪፖርት)'),
        ('absent', 'Monthly Absent List Report (የቀሪ ሰራተኞች ዝርዝር ሪፖርት)'),
        ('deduction', 'Monthly Deduction Report (የተቀናሽ ሪፖርት)'),
        ('all', 'All Reports in One Workbook (ሁሉንም በአንድ ላይ)'),
    ], string='Report Type', default='overtime', required=True)

    filter_by = fields.Selection([
        ('batch', 'By Payslip Batch (በደመወዝ ባች)'),
        ('date', 'By Date Period (በቀን ክልል)'),
    ], string='Filter By', default='batch', required=True)

    payslip_run_id = fields.Many2one(
        'hr.payslip.run',
        string='Payslip Batch',
        domain="[('company_id', '=', company_id)]",
    )
    date_from = fields.Date(
        string='Start Date',
        default=lambda self: fields.Date.today() + relativedelta(day=1),
        required=True,
    )
    date_to = fields.Date(
        string='End Date',
        default=lambda self: fields.Date.today() + relativedelta(day=1, months=1, days=-1),
        required=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        required=True,
    )

    # Ethiopian Date & Title Settings
    ethiopian_month = fields.Selection(
        eth_utils.ETHIOPIAN_MONTH_SELECTION,
        string='Ethiopian Month',
        default='1',
        required=True,
    )
    ethiopian_year = fields.Integer(
        string='Ethiopian Year',
        default=2019,
        required=True,
    )
    report_title = fields.Char(
        string='Report Title Header',
        help='Header printed at the top of the report. Automatically updated when month/year changes.',
    )

    # Filtering Options
    employee_classification = fields.Selection([
        ('all', 'All Accessible Classifications'),
        ('head_office', 'Head Office (ዋና መ/ቤት)'),
        ('bebeka_head_office', 'Bebeka Head Office (የበበቃ ዋና መ/ቤት)'),
        ('jimma_head_office', 'Jimma Head Office (የጅማ ዋና መ/ቤት)'),
        ('farm', 'Farm (የእርሻ)'),
        ('cpw', 'CPW'),
        ('temporary', 'Temporary (ጊዜያዊ)'),
        ('zemach', 'Zemach / Seasonal (ዘማች)'),
    ], string='Employee Classification', default='all')

    department_id = fields.Many2one(
        'hr.department',
        string='Department',
        help='Optional filter by department.',
    )
    only_with_overtime = fields.Boolean(
        string='Only Employees with Overtime',
        default=True,
        help='If checked, only employees who performed overtime in this period will be listed.',
    )
    only_with_absent = fields.Boolean(
        string='Only Employees with Absent Days',
        default=True,
        help='If checked, only employees with unexcused absent days will be listed.',
    )
    only_with_allowance = fields.Boolean(
        string='Only Employees with Allowances',
        default=True,
        help='If checked, only employees receiving allowances will be listed.',
    )

    # Specific Deduction Rule (when report_type is 'deduction')
    deduction_rule_id = fields.Many2one(
        'hr.salary.rule',
        string='Deduction Item',
        domain="[('category_id.code', '=', 'DED')]",
        help='Select specific deduction rule (e.g. Oil Deduction, Flour Deduction, Labor Union). Leave empty for Oil Deduction.',
    )

    # Signatures
    prepared_by = fields.Char(string='Prepared By', default='')
    checked_by = fields.Char(string='Checked By', default='')
    verified_by = fields.Char(string='Verified By', default='')
    approved_by = fields.Char(string='Approved By', default='')

    @api.model
    def default_get(self, fields_list):
        res = super(HrPayrollMonthlyReportWizard, self).default_get(fields_list)
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids', [])

        default_date = date.today()
        if active_model == 'hr.payslip.run' and active_ids:
            run = self.env['hr.payslip.run'].browse(active_ids[0])
            res['filter_by'] = 'batch'
            res['payslip_run_id'] = run.id
            if run.date_start:
                res['date_from'] = run.date_start
                default_date = run.date_start
            if run.date_end:
                res['date_to'] = run.date_end
            if hasattr(run, 'company_id') and run.company_id:
                res['company_id'] = run.company_id.id
        elif active_model == 'hr.payslip' and active_ids:
            slips = self.env['hr.payslip'].browse(active_ids).filtered(lambda s: s.state != 'cancel')
            if slips:
                res['filter_by'] = 'batch' if slips[0].payslip_run_id else 'date'
                if slips[0].payslip_run_id:
                    res['payslip_run_id'] = slips[0].payslip_run_id.id
                if slips[0].date_from:
                    res['date_from'] = slips[0].date_from
                    default_date = slips[0].date_from
                if slips[0].date_to:
                    res['date_to'] = slips[0].date_to

        # Convert default date to Ethiopian Month and Year
        eth_conv = eth_utils.gregorian_to_ethiopian(default_date)
        if eth_conv:
            res['ethiopian_year'] = eth_conv[0]
            res['ethiopian_month'] = str(eth_conv[1])

        # Pre-select Oil Deduction rule if exists
        oil_rule = self.env['hr.salary.rule'].search([('code', '=', 'DED_OIL')], limit=1)
        if oil_rule:
            res['deduction_rule_id'] = oil_rule.id

        # Compute initial title
        m_idx = int(res.get('ethiopian_month', '1'))
        m_name = eth_utils.ETHIOPIAN_MONTHS_AMHARIC[m_idx] if 1 <= m_idx <= 13 else 'መስከረም'
        yr = res.get('ethiopian_year', 2019)
        rtype = res.get('report_type', 'overtime')
        res['report_title'] = self._build_title(rtype, m_name, yr)

        return res

    @api.onchange('filter_by', 'payslip_run_id', 'date_from')
    def _onchange_dates_or_batch(self):
        ref_date = self.date_from
        if self.filter_by == 'batch' and self.payslip_run_id:
            if self.payslip_run_id.date_start:
                self.date_from = self.payslip_run_id.date_start
                ref_date = self.payslip_run_id.date_start
            if self.payslip_run_id.date_end:
                self.date_to = self.payslip_run_id.date_end
        if ref_date:
            eth_conv = eth_utils.gregorian_to_ethiopian(ref_date)
            if eth_conv:
                self.ethiopian_year = eth_conv[0]
                self.ethiopian_month = str(eth_conv[1])
        self._update_report_title()

    @api.onchange('report_type', 'ethiopian_month', 'ethiopian_year', 'deduction_rule_id')
    def _onchange_report_settings(self):
        self._update_report_title()

    def _update_report_title(self):
        m_idx = int(self.ethiopian_month or '1')
        m_name = eth_utils.ETHIOPIAN_MONTHS_AMHARIC[m_idx] if 1 <= m_idx <= 13 else 'መስከረም'
        yr = self.ethiopian_year or 2019
        self.report_title = self._build_title(self.report_type, m_name, yr, self.deduction_rule_id)

    def _build_title(self, rtype, m_name, yr, deduction_rule=None):
        if rtype == 'overtime':
            return f"Overtime done for the Month of {m_name} {yr}"
        elif rtype == 'allowance':
            return f"Payroll Allowance for the Month of {m_name} {yr}"
        elif rtype == 'absent':
            return f"Absent list for the Month of {m_name} {yr}"
        elif rtype == 'deduction':
            d_name = deduction_rule.name.split('(')[0].strip() if deduction_rule else "Oil Deduction"
            return f"Payroll Deduction ({d_name}) for the Month of {m_name} {yr}"
        else:
            return f"Payroll Statements for the Month of {m_name} {yr}"

    # ---------------------------------------------------------
    # Core Data Extraction Engine
    # ---------------------------------------------------------
    def _get_target_payslips(self):
        self.ensure_one()
        slips = self.env['hr.payslip']

        if self.filter_by == 'batch':
            if not self.payslip_run_id:
                raise UserError(_("Please select a Payslip Batch."))
            slips = self.payslip_run_id.slip_ids.filtered(lambda s: s.state != 'cancel')
        else:
            if self.date_from > self.date_to:
                raise UserError(_("Start Date cannot be later than End Date."))
            domain = [
                ('date_from', '>=', self.date_from),
                ('date_to', '<=', self.date_to),
                ('company_id', '=', self.company_id.id),
                ('state', '!=', 'cancel'),
            ]
            slips = self.env['hr.payslip'].search(domain)

        if not slips:
            raise UserError(_("No valid payslips found for the selected batch or period."))

        # Apply classification filter
        if self.employee_classification and self.employee_classification != 'all':
            slips = slips.filtered(lambda s: getattr(s.employee_id, 'farm_employee_type', False) == self.employee_classification)

        # Apply department filter
        if self.department_id:
            slips = slips.filtered(lambda s: s.employee_id.department_id == self.department_id)

        # Enforce current user classification security
        user = self.env.user
        if hasattr(user, '_get_allowed_farm_employee_types'):
            allowed = user._get_allowed_farm_employee_types()
            if allowed and 'all' not in allowed:
                slips = slips.filtered(lambda s: getattr(s.employee_id, 'farm_employee_type', False) in allowed)

        return slips.sorted(key=lambda s: (s.employee_id.department_id.name or '', s.employee_id.name or ''))

    def _get_overtime_data(self, slips):
        """
        Calculates Overtime rows matching template image:
        No., Name, salary, Normal Hour (Hour, Amount), Night Hour (Hour, Amount),
        Weekend hour (Hour, Amount), Holiday Hour (Hour, Amount), Total
        """
        rows = []
        tot_salary = 0.0
        tot_norm_h = 0.0
        tot_norm_amt = 0.0
        tot_night_h = 0.0
        tot_night_amt = 0.0
        tot_wk_h = 0.0
        tot_wk_amt = 0.0
        tot_hol_h = 0.0
        tot_hol_amt = 0.0
        tot_grand = 0.0

        idx = 1
        for slip in slips:
            emp = slip.employee_id
            contract = slip.contract_id
            salary = contract.wage if contract else (slip.wage or 0.0)

            # Hours
            norm_h = slip.ot_day_hours or 0.0
            night_h = slip.ot_night_hours or 0.0
            wk_h = slip.ot_weekend_hours or 0.0
            hol_h = slip.ot_holiday_hours or 0.0
            tot_h = norm_h + night_h + wk_h + hol_h

            if self.only_with_overtime and tot_h <= 0.0:
                continue

            # Rates & Calculations: 208 working hours standard
            work_hours = contract.monthly_working_hours or 208.0 if contract else 208.0
            base_hourly = (salary / work_hours) if work_hours else 0.0
            norm_rate = contract.ot_day_rate or (base_hourly * 1.5) if contract else (base_hourly * 1.5)
            night_rate = contract.ot_night_rate or (base_hourly * 1.75) if contract else (base_hourly * 1.75)
            wk_rate = contract.ot_weekend_rate or (base_hourly * 2.0) if contract else (base_hourly * 2.0)
            hol_rate = contract.ot_holiday_rate or (base_hourly * 2.5) if contract else (base_hourly * 2.5)

            norm_amt = round(norm_h * norm_rate, 2)
            night_amt = round(night_h * night_rate, 2)
            wk_amt = round(wk_h * wk_rate, 2)
            hol_amt = round(hol_h * hol_rate, 2)
            row_tot = norm_amt + night_amt + wk_amt + hol_amt

            rows.append({
                'no': idx,
                'name': emp.name or '',
                'salary': salary,
                'norm_h': norm_h,
                'norm_amt': norm_amt,
                'night_h': night_h,
                'night_amt': night_amt,
                'wk_h': wk_h,
                'wk_amt': wk_amt,
                'hol_h': hol_h,
                'hol_amt': hol_amt,
                'total': row_tot,
            })

            tot_salary += salary
            tot_norm_h += norm_h
            tot_norm_amt += norm_amt
            tot_night_h += night_h
            tot_night_amt += night_amt
            tot_wk_h += wk_h
            tot_wk_amt += wk_amt
            tot_hol_h += hol_h
            tot_hol_amt += hol_amt
            tot_grand += row_tot
            idx += 1

        totals = {
            'tot_salary': tot_salary,
            'tot_norm_h': tot_norm_h,
            'tot_norm_amt': tot_norm_amt,
            'tot_night_h': tot_night_h,
            'tot_night_amt': tot_night_amt,
            'tot_wk_h': tot_wk_h,
            'tot_wk_amt': tot_wk_amt,
            'tot_hol_h': tot_hol_h,
            'tot_hol_amt': tot_hol_amt,
            'tot_grand': tot_grand,
        }
        return {'rows': rows, 'totals': totals}

    def _get_allowance_data(self, slips):
        """
        Calculates Allowance rows matching template image:
        No, Employee, Allowance [Acting, Indeminity Allowance, Service, transp repl, Untaxed Transportation Allowance], Total
        """
        # Column definitions matching user image
        columns = [
            {'key': 'acting', 'title': 'Acting', 'codes': ['ALW_ACTING_POSITION', 'ACTING', 'ACT']},
            {'key': 'indemnity', 'title': 'Indeminity Allowance', 'codes': ['ALW_CASH_INDEMNITY', 'CASH_INDEMNITY', 'INDEMNITY']},
            {'key': 'service', 'title': 'Service', 'codes': ['ALW_SERVICE', 'SERVICE_ALLOWANCE', 'DED_SERVICE_CHARGE']},
            {'key': 'transp_repl', 'title': 'transp repl', 'codes': ['ALW_TRANSPORT_REPL', 'CA', 'CAGG', 'TRANS_REPL']},
            {'key': 'untaxed_transp', 'title': 'Untaxed Transportation Allowance', 'codes': ['ALW_TRANSPORT', 'TTRA_EXEMPT', 'TRANSPORT', 'UNTAXED_TRANS']},
        ]

        rows = []
        col_totals = {col['key']: 0.0 for col in columns}
        grand_total = 0.0

        idx = 1
        for slip in slips:
            emp = slip.employee_id
            slip_rule_map = {line.code: line.total for line in slip.line_ids}

            # Map amounts
            row_vals = {}
            row_sum = 0.0
            for col in columns:
                val = 0.0
                for c in col['codes']:
                    if c in slip_rule_map:
                        val += slip_rule_map[c]
                # Also check contract fields if rule map had 0
                if val == 0.0 and slip.contract_id:
                    if col['key'] == 'acting' and hasattr(slip.contract_id, 'acting_allowance'):
                        val = getattr(slip.contract_id, 'acting_allowance') or 0.0
                    elif col['key'] == 'indemnity' and hasattr(slip.contract_id, 'cash_indemnity'):
                        val = getattr(slip.contract_id, 'cash_indemnity') or 0.0
                    elif col['key'] == 'untaxed_transp' and hasattr(slip.contract_id, 'transport_allowance'):
                        val = getattr(slip.contract_id, 'transport_allowance') or 0.0

                row_vals[col['key']] = round(val, 2)
                row_sum += val

            if self.only_with_allowance and row_sum <= 0.0:
                continue

            rows.append({
                'no': idx,
                'name': emp.name or '',
                'values': row_vals,
                'total': round(row_sum, 2),
            })

            for col in columns:
                col_totals[col['key']] += row_vals[col['key']]
            grand_total += row_sum
            idx += 1

        return {
            'columns': columns,
            'rows': rows,
            'col_totals': col_totals,
            'grand_total': round(grand_total, 2),
        }

    def _get_absent_data(self, slips):
        """
        Calculates Absent rows matching template image:
        No., Name, Basic salary, Absent days, Absent deduction
        Deduction formula: (Basic salary / 26) * Absent days
        """
        rows = []
        tot_salary = 0.0
        tot_days = 0.0
        tot_deduction = 0.0

        idx = 1
        for slip in slips:
            emp = slip.employee_id
            contract = slip.contract_id
            basic_salary = contract.wage if contract else (slip.wage or 0.0)

            # Absent days from payslip or sheets
            abs_days = slip.approved_absent_days or 0.0
            if abs_days == 0.0 and slip.approved_absent_hours:
                abs_days = round(slip.approved_absent_hours / 8.0, 1)

            # Deduction amount: check payslip line, or formula (salary / 26) * days
            if slip.absent_deduction_amount:
                ded_amt = slip.absent_deduction_amount
            elif abs_days > 0:
                ded_amt = round((basic_salary / 26.0) * abs_days, 2)
            else:
                ded_amt = 0.0

            if self.only_with_absent and abs_days <= 0.0 and ded_amt <= 0.0:
                continue

            rows.append({
                'no': idx,
                'name': emp.name or '',
                'salary': basic_salary,
                'absent_days': abs_days,
                'absent_deduction': ded_amt,
            })

            tot_salary += basic_salary
            tot_days += abs_days
            tot_deduction += ded_amt
            idx += 1

        totals = {
            'tot_salary': tot_salary,
            'tot_days': tot_days,
            'tot_deduction': tot_deduction,
        }
        return {'rows': rows, 'totals': totals}

    def _get_deduction_data(self, slips):
        """
        Calculates Deduction rows matching template image:
        No, Employee, <Deduction Item Name>
        """
        rule = self.deduction_rule_id
        rule_code = rule.code if rule else 'DED_OIL'
        rule_label = rule.name.split('(')[0].strip() if rule else 'Oil Deduction'

        rows = []
        tot_amt = 0.0

        idx = 1
        for slip in slips:
            emp = slip.employee_id
            slip_rule_map = {line.code: line.total for line in slip.line_ids}
            amt = abs(slip_rule_map.get(rule_code, 0.0))

            # If 0, check contract if available
            if amt == 0.0 and slip.contract_id and hasattr(slip.contract_id, 'oil_deduction') and rule_code == 'DED_OIL':
                amt = abs(getattr(slip.contract_id, 'oil_deduction') or 0.0)

            if amt <= 0.0:
                continue

            rows.append({
                'no': idx,
                'name': emp.name or '',
                'amount': amt,
            })
            tot_amt += amt
            idx += 1

        return {
            'rule_label': rule_label,
            'rows': rows,
            'tot_amt': tot_amt,
        }

    # ---------------------------------------------------------
    # Actions: Print PDF & Export Excel
    # ---------------------------------------------------------
    def action_print_pdf(self):
        """ Print QWeb Landscape PDF report """
        self.ensure_one()
        slips = self._get_target_payslips()
        if not slips:
            raise UserError(_("No payslips found matching your criteria."))

        data = {
            'report_title': self.report_title,
            'report_type': self.report_type,
            'prepared_by': self.prepared_by or '',
            'checked_by': self.checked_by or '',
            'verified_by': self.verified_by or '',
            'approved_by': self.approved_by or '',
        }

        if self.report_type == 'overtime':
            data['ot_data'] = self._get_overtime_data(slips)
        elif self.report_type == 'allowance':
            data['alw_data'] = self._get_allowance_data(slips)
        elif self.report_type == 'absent':
            data['abs_data'] = self._get_absent_data(slips)
        elif self.report_type == 'deduction':
            data['ded_data'] = self._get_deduction_data(slips)
        elif self.report_type == 'all':
            data['ot_data'] = self._get_overtime_data(slips)
            data['alw_data'] = self._get_allowance_data(slips)
            data['abs_data'] = self._get_absent_data(slips)
            data['ded_data'] = self._get_deduction_data(slips)

        report = self.env.ref('attendance_ot_portal_approval.action_report_monthly_payroll_statement')
        return report.report_action(self, data=data)

    def action_export_xlsx(self):
        """ Generates and downloads professional Excel (.xlsx) report """
        self.ensure_one()
        slips = self._get_target_payslips()
        if not slips:
            raise UserError(_("No payslips found matching your criteria."))

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})

        # --- Formats & Styles ---
        fmt_title = workbook.add_format({
            'bold': True,
            'font_size': 16,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
        })
        fmt_th = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True,
            'bg_color': '#FFFFFF',
        })
        fmt_th_highlight = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
            'text_wrap': True,
            'bg_color': '#C8D6AF',  # Soft greenish matching deduction template
        })
        fmt_td_center = workbook.add_format({
            'font_size': 9.5,
            'font_name': 'Times New Roman',
            'align': 'center',
            'valign': 'vcenter',
            'border': 1,
        })
        fmt_td_name = workbook.add_format({
            'font_size': 9.5,
            'font_name': 'Times New Roman',
            'align': 'left',
            'valign': 'vcenter',
            'border': 1,
        })
        fmt_td_num = workbook.add_format({
            'font_size': 9.5,
            'font_name': 'Times New Roman',
            'align': 'right',
            'valign': 'vcenter',
            'num_format': '#,##0.00',
            'border': 1,
        })
        fmt_td_dec = workbook.add_format({
            'font_size': 9.5,
            'font_name': 'Times New Roman',
            'align': 'right',
            'valign': 'vcenter',
            'num_format': '0.00',
            'border': 1,
        })
        fmt_tot_label = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'right',
            'valign': 'vcenter',
            'border': 1,
        })
        fmt_tot_num = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'right',
            'valign': 'vcenter',
            'num_format': '#,##0.00',
            'border': 1,
        })
        fmt_tot_dec = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'align': 'right',
            'valign': 'vcenter',
            'num_format': '0.00',
            'border': 1,
        })
        fmt_sign_label = workbook.add_format({
            'bold': True,
            'font_size': 10,
            'font_name': 'Times New Roman',
            'valign': 'vcenter',
        })
        fmt_sign_line = workbook.add_format({
            'font_size': 10,
            'font_name': 'Times New Roman',
            'valign': 'vcenter',
        })

        # Helper to render signature footer
        def write_signatures(ws, row, last_col):
            row += 2
            col_gap = max(1, last_col // 4)
            signs = [
                ('Prepared BY:', self.prepared_by or '___________________'),
                ('Checked BY:', self.checked_by or '___________________'),
                ('Verified BY:', self.verified_by or '___________________'),
                ('Approved By:', self.approved_by or '___________________'),
            ]
            c = 0
            for label, val in signs:
                ws.write(row, c, f"{label} {val}", fmt_sign_label)
                c += col_gap

        # ----------------- OVERTIME SHEET -----------------
        if self.report_type in ('overtime', 'all'):
            ws = workbook.add_worksheet('Overtime Report')
            ot_data = self._get_overtime_data(slips)
            rows = ot_data['rows']
            totals = ot_data['totals']

            # Title
            ot_title = self.report_title if self.report_type == 'overtime' else f"Overtime done for the Month of {eth_utils.ETHIOPIAN_MONTHS_AMHARIC[int(self.ethiopian_month)]} {self.ethiopian_year}"
            ws.merge_range(1, 0, 1, 11, ot_title, fmt_title)
            ws.set_row(1, 30)

            # Two-tier Headers
            ws.merge_range(3, 0, 4, 0, "No.", fmt_th)
            ws.merge_range(3, 1, 4, 1, "Name", fmt_th)
            ws.merge_range(3, 2, 4, 2, "salary", fmt_th)
            ws.merge_range(3, 3, 3, 4, "Normal Hour", fmt_th)
            ws.write(4, 3, "Hour", fmt_th)
            ws.write(4, 4, "Amount", fmt_th)
            ws.merge_range(3, 5, 3, 6, "Night Hour", fmt_th)
            ws.write(4, 5, "Hour", fmt_th)
            ws.write(4, 6, "Amount", fmt_th)
            ws.merge_range(3, 7, 3, 8, "Weekend hour", fmt_th)
            ws.write(4, 7, "Hour", fmt_th)
            ws.write(4, 8, "Amount", fmt_th)
            ws.merge_range(3, 9, 3, 10, "Holiday Hour", fmt_th)
            ws.write(4, 9, "Hour", fmt_th)
            ws.write(4, 10, "Amount", fmt_th)
            ws.merge_range(3, 11, 4, 11, "Total", fmt_th)

            r = 5
            for row in rows:
                ws.write(r, 0, row['no'], fmt_td_center)
                ws.write(r, 1, row['name'], fmt_td_name)
                ws.write(r, 2, row['salary'], fmt_td_num)
                ws.write(r, 3, row['norm_h'], fmt_td_dec)
                ws.write(r, 4, row['norm_amt'], fmt_td_num)
                ws.write(r, 5, row['night_h'], fmt_td_dec)
                ws.write(r, 6, row['night_amt'], fmt_td_num)
                ws.write(r, 7, row['wk_h'], fmt_td_dec)
                ws.write(r, 8, row['wk_amt'], fmt_td_num)
                ws.write(r, 9, row['hol_h'], fmt_td_dec)
                ws.write(r, 10, row['hol_amt'], fmt_td_num)
                ws.write(r, 11, row['total'], fmt_td_num)
                r += 1

            # Grand Total Row
            ws.merge_range(r, 0, r, 1, "Total", fmt_tot_label)
            ws.write(r, 2, totals['tot_salary'], fmt_tot_num)
            ws.write(r, 3, totals['tot_norm_h'], fmt_tot_dec)
            ws.write(r, 4, totals['tot_norm_amt'], fmt_tot_num)
            ws.write(r, 5, totals['tot_night_h'], fmt_tot_dec)
            ws.write(r, 6, totals['tot_night_amt'], fmt_tot_num)
            ws.write(r, 7, totals['tot_wk_h'], fmt_tot_dec)
            ws.write(r, 8, totals['tot_wk_amt'], fmt_tot_num)
            ws.write(r, 9, totals['tot_hol_h'], fmt_tot_dec)
            ws.write(r, 10, totals['tot_hol_amt'], fmt_tot_num)
            ws.write(r, 11, totals['tot_grand'], fmt_tot_num)

            # Column widths
            ws.set_column(0, 0, 6)
            ws.set_column(1, 1, 24)
            ws.set_column(2, 2, 13)
            ws.set_column(3, 10, 11)
            ws.set_column(11, 11, 14)

            write_signatures(ws, r, 11)

        # ----------------- ALLOWANCE SHEET -----------------
        if self.report_type in ('allowance', 'all'):
            ws = workbook.add_worksheet('Allowance Report')
            alw_data = self._get_allowance_data(slips)
            cols = alw_data['columns']
            rows = alw_data['rows']
            num_cols = len(cols)

            alw_title = self.report_title if self.report_type == 'allowance' else f"Payroll Allowance for the Month of {eth_utils.ETHIOPIAN_MONTHS_AMHARIC[int(self.ethiopian_month)]} {self.ethiopian_year}"
            ws.merge_range(1, 0, 1, 2 + num_cols, alw_title, fmt_title)
            ws.set_row(1, 30)

            ws.merge_range(3, 0, 4, 0, "No", fmt_th)
            ws.merge_range(3, 1, 4, 1, "Employee", fmt_th)
            ws.merge_range(3, 2, 3, 1 + num_cols, "Allowance", fmt_th)
            for c_idx, col in enumerate(cols):
                ws.write(4, 2 + c_idx, col['title'], fmt_th)
            ws.merge_range(3, 2 + num_cols, 4, 2 + num_cols, "Total", fmt_th)

            r = 5
            for row in rows:
                ws.write(r, 0, row['no'], fmt_td_center)
                ws.write(r, 1, row['name'], fmt_td_name)
                for c_idx, col in enumerate(cols):
                    val = row['values'][col['key']]
                    if val > 0:
                        ws.write(r, 2 + c_idx, val, fmt_td_num)
                    else:
                        ws.write(r, 2 + c_idx, "", fmt_td_center)
                ws.write(r, 2 + num_cols, row['total'], fmt_td_num)
                r += 1

            # Total Row
            ws.merge_range(r, 0, r, 1, "Total", fmt_tot_label)
            for c_idx, col in enumerate(cols):
                ws.write(r, 2 + c_idx, alw_data['col_totals'][col['key']], fmt_tot_num)
            ws.write(r, 2 + num_cols, alw_data['grand_total'], fmt_tot_num)

            ws.set_column(0, 0, 6)
            ws.set_column(1, 1, 24)
            for c_idx in range(num_cols):
                ws.set_column(2 + c_idx, 2 + c_idx, 16)
            ws.set_column(2 + num_cols, 2 + num_cols, 14)

            write_signatures(ws, r, 2 + num_cols)

        # ----------------- ABSENT SHEET -----------------
        if self.report_type in ('absent', 'all'):
            ws = workbook.add_worksheet('Absent List')
            abs_data = self._get_absent_data(slips)
            rows = abs_data['rows']
            totals = abs_data['totals']

            abs_title = self.report_title if self.report_type == 'absent' else f"Absent list for the Month of {eth_utils.ETHIOPIAN_MONTHS_AMHARIC[int(self.ethiopian_month)]} {self.ethiopian_year}"
            ws.merge_range(1, 0, 1, 4, abs_title, fmt_title)
            ws.set_row(1, 30)

            ws.write(3, 0, "No.", fmt_th)
            ws.write(3, 1, "Name", fmt_th)
            ws.write(3, 2, "Basic salary", fmt_th)
            ws.write(3, 3, "Absent days", fmt_th)
            ws.write(3, 4, "Absent deduction", fmt_th)

            r = 4
            for row in rows:
                ws.write(r, 0, row['no'], fmt_td_center)
                ws.write(r, 1, row['name'], fmt_td_name)
                ws.write(r, 2, row['salary'], fmt_td_num)
                ws.write(r, 3, row['absent_days'], fmt_td_dec)
                ws.write(r, 4, row['absent_deduction'], fmt_td_num)
                r += 1

            ws.merge_range(r, 0, r, 1, "Total", fmt_tot_label)
            ws.write(r, 2, totals['tot_salary'], fmt_tot_num)
            ws.write(r, 3, totals['tot_days'], fmt_tot_dec)
            ws.write(r, 4, totals['tot_deduction'], fmt_tot_num)

            ws.set_column(0, 0, 6)
            ws.set_column(1, 1, 25)
            ws.set_column(2, 2, 16)
            ws.set_column(3, 3, 14)
            ws.set_column(4, 4, 18)

            write_signatures(ws, r, 4)

        # ----------------- DEDUCTION SHEET -----------------
        if self.report_type in ('deduction', 'all'):
            ws = workbook.add_worksheet('Deduction Report')
            ded_data = self._get_deduction_data(slips)
            rows = ded_data['rows']

            ded_title = self.report_title if self.report_type == 'deduction' else f"Payroll Deduction for the Month of {eth_utils.ETHIOPIAN_MONTHS_AMHARIC[int(self.ethiopian_month)]} {self.ethiopian_year}"
            ws.merge_range(1, 0, 1, 2, ded_title, fmt_title)
            ws.set_row(1, 30)

            ws.write(3, 0, "No", fmt_th_highlight)
            ws.write(3, 1, "Employee", fmt_th_highlight)
            ws.write(3, 2, ded_data['rule_label'], fmt_th_highlight)

            r = 4
            for row in rows:
                ws.write(r, 0, row['no'], fmt_td_center)
                ws.write(r, 1, row['name'], fmt_td_name)
                ws.write(r, 2, row['amount'], fmt_td_num)
                r += 1

            ws.merge_range(r, 0, r, 1, "Total", fmt_tot_label)
            ws.write(r, 2, ded_data['tot_amt'], fmt_tot_num)

            ws.set_column(0, 0, 6)
            ws.set_column(1, 1, 28)
            ws.set_column(2, 2, 18)

            write_signatures(ws, r, 2)

        workbook.close()
        xlsx_data = output.getvalue()

        # Filename
        clean_name = self.report_title.replace('/', '-').replace(' ', '_').replace(':', '')
        filename = f"{clean_name}.xlsx"

        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(xlsx_data),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })

        return {
            'type': 'ir.actions.act_url',
            'url': f"/web/content/{attachment.id}?download=true",
            'target': 'self',
        }

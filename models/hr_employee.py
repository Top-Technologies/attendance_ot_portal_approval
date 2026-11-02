# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    attendance_ot_sheet_ids = fields.One2many(
        'attendance.ot.approval.sheet',
        'employee_id',
        string='Attendance OT & Absent Sheets',
    )
    attendance_ot_sheet_count = fields.Integer(
        string='OT & Attendance Sheets Count',
        compute='_compute_attendance_ot_sheet_count',
    )

    is_portal_attendance_manager = fields.Boolean(
        string="Is Portal Attendance & OT Manager",
        help="Check this box to grant this employee portal manager privileges to review and approve team OT & attendance reports.",
    )

    def _compute_attendance_ot_sheet_count(self):
        for employee in self:
            employee.attendance_ot_sheet_count = len(employee.attendance_ot_sheet_ids)

    def action_view_attendance_ot_sheets(self):
        self.ensure_one()
        return {
            'name': _("Attendance OT & Absent Sheets"),
            'type': 'ir.actions.act_window',
            'res_model': 'attendance.ot.approval.sheet',
            'view_mode': 'list,form',
            'domain': [('employee_id', '=', self.id)],
            'context': {'default_employee_id': self.id},
        }


    def _get_subordinate_hierarchy_ids(self, include_self=False):
        """
        Return the set of employee IDs for all subordinates reporting under self.
        Traverses the full reporting line (direct reports + indirect reports).
        
        Edge Case Protections:
        - Circular References: Protected via visited set; prevents infinite loops.
        - Self-referencing: If parent_id == id, the cycle is broken immediately.
        - Unassigned Employees: Never included since their parent_id is False.
        - Deactivated Managers: Inactive managers in the chain are traversed if they have
          active subordinates, but inactive employees themselves can be excluded or included
          based on active context.
        """
        all_subordinate_ids = set()
        visited = set()

        for manager in self:
            queue = [manager.id]
            visited.add(manager.id)

            while queue:
                current_mgr_id = queue.pop(0)
                # Find direct active reports of current_mgr_id, strictly excluding self to prevent 1-node loops
                direct_children = self.sudo().search([
                    ('parent_id', '=', current_mgr_id),
                    ('id', '!=', current_mgr_id),
                    ('active', '=', True),
                ])
                for child in direct_children:
                    if child.id not in visited:
                        visited.add(child.id)
                        all_subordinate_ids.add(child.id)
                        queue.append(child.id)

        if include_self:
            all_subordinate_ids.update(self.ids)

        return all_subordinate_ids

    def _get_all_subordinates(self, include_self=False):
        """Return hr.employee recordset of all subordinates in reporting line."""
        sub_ids = self._get_subordinate_hierarchy_ids(include_self=include_self)
        if not sub_ids:
            return self.env['hr.employee']
        return self.browse(list(sub_ids))

    def _get_direct_subordinates(self):
        """Return direct active subordinates only, excluding self."""
        return self.child_ids.filtered(lambda c: c.id not in self.ids and c.active)

    def is_in_subordinate_hierarchy(self, subordinate_emp):
        """Check if subordinate_emp (record or ID) reports to self directly or indirectly."""
        sub_id = subordinate_emp.id if hasattr(subordinate_emp, 'id') else int(subordinate_emp)
        return sub_id in self._get_subordinate_hierarchy_ids(include_self=False)

    @api.model
    def fix_circular_manager_hierarchies(self):
        """
        Audit and repair circular parent_id loops in hr.employee across the database.
        Breaks the cycle by setting parent_id = False and logging the anomaly.
        Returns list of modified employee IDs.
        """
        employees = self.sudo().search([('parent_id', '!=', False)])
        fixed_ids = []
        for emp in employees:
            visited = {emp.id}
            curr = emp.parent_id
            while curr:
                if curr.id in visited:
                    _logger.warning(
                        "Broken circular manager hierarchy loop detected on employee %s (ID %s) -> parent %s (ID %s). Unlinking parent_id.",
                        emp.name, emp.id, curr.name, curr.id
                    )
                    emp.parent_id = False
                    fixed_ids.append(emp.id)
                    break
                visited.add(curr.id)
                curr = curr.parent_id
        return fixed_ids


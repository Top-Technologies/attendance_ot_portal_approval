# -*- coding: utf-8 -*-
from datetime import date, timedelta
from odoo.tests.common import TransactionCase, tagged
from odoo.exceptions import UserError, AccessError


@tagged('post_install', '-at_install', 'attendance_approval')
class TestAttendanceHierarchyApproval(TransactionCase):
    """
    Test suite for Attendance & OT hierarchy-scoped approval flows:
    1. Direct Manager Scope: Direct reports only.
    2. Manager of Managers Scope: Direct + full indirect subordinate subtree.
    3. Unassigned Employees: Never accessible to managers; only HR Admins can view/approve.
    4. Cross-Team Access Prevention: Server-side rejection of out-of-scope approvals.
    5. Self-Approval Prohibition: Strict server-side block on approving own sheets.
    6. Circular References: Loop breaking and protection against infinite recursion.
    7. Batch Approval Scoping: Only reporting line sheets are processed.
    """

    @classmethod
    def _create_employee(cls, vals):
        default_vals = {
            'birthday': date(1990, 1, 1),
            'has_medical_certificate': True,
            'company_id': cls.company.id,
        }
        default_vals.update(vals)
        return cls.env['hr.employee'].create(default_vals)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company

        # Groups
        cls.group_portal_manager = cls.env.ref('zkteco_attendance.group_zkteco_manager')
        cls.group_hr_admin = cls.env.ref('zkteco_attendance.group_zkteco_admin')
        cls.group_ot_manager = cls.env.ref('attendance_ot_portal_approval.group_attendance_ot_manager')
        cls.group_hr_manager = cls.env.ref('hr.group_hr_manager')
        cls.group_system_admin = cls.env.ref('base.group_erp_manager')
        cls.group_internal_user = cls.env.ref('base.group_user')

        # Create Users
        cls.hr_admin_user = cls.env['res.users'].create({
            'name': 'HR Admin User',
            'login': 'test_hr_admin@example.com',
            'email': 'test_hr_admin@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'groups_id': [(6, 0, [
                cls.group_internal_user.id,
                cls.group_hr_admin.id,
                cls.group_ot_manager.id,
                cls.group_hr_manager.id,
                cls.group_system_admin.id,
            ])],
        })

        cls.top_mgr_user = cls.env['res.users'].create({
            'name': 'Top Director User',
            'login': 'test_top_mgr@example.com',
            'email': 'test_top_mgr@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'groups_id': [(6, 0, [cls.group_internal_user.id, cls.group_portal_manager.id])],
        })

        cls.middle_mgr_user = cls.env['res.users'].create({
            'name': 'Middle Manager User',
            'login': 'test_middle_mgr@example.com',
            'email': 'test_middle_mgr@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'groups_id': [(6, 0, [cls.group_internal_user.id, cls.group_portal_manager.id])],
        })

        cls.other_mgr_user = cls.env['res.users'].create({
            'name': 'Other Manager User',
            'login': 'test_other_mgr@example.com',
            'email': 'test_other_mgr@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'groups_id': [(6, 0, [cls.group_internal_user.id, cls.group_portal_manager.id])],
        })

        cls.subordinate_user = cls.env['res.users'].create({
            'name': 'Subordinate User',
            'login': 'test_subordinate@example.com',
            'email': 'test_subordinate@example.com',
            'company_id': cls.company.id,
            'company_ids': [(6, 0, [cls.company.id])],
            'groups_id': [(6, 0, [cls.group_internal_user.id])],
        })

        # Create Hierarchy:
        # Top Director
        #   -> Middle Manager
        #        -> Subordinate 1
        #        -> Subordinate 2
        # Other Manager
        #   -> Other Subordinate
        # Unassigned Employee (parent_id = False)

        cls.top_mgr_emp = cls._create_employee({
            'name': 'Top Director',
            'user_id': cls.top_mgr_user.id,
            'is_portal_attendance_manager': True,
        })

        cls.middle_mgr_emp = cls._create_employee({
            'name': 'Middle Manager',
            'user_id': cls.middle_mgr_user.id,
            'parent_id': cls.top_mgr_emp.id,
            'is_portal_attendance_manager': True,
        })

        cls.subordinate_1_emp = cls._create_employee({
            'name': 'Subordinate One',
            'user_id': cls.subordinate_user.id,
            'parent_id': cls.middle_mgr_emp.id,
        })

        cls.subordinate_2_emp = cls._create_employee({
            'name': 'Subordinate Two',
            'parent_id': cls.middle_mgr_emp.id,
        })

        cls.other_mgr_emp = cls._create_employee({
            'name': 'Other Manager',
            'user_id': cls.other_mgr_user.id,
            'is_portal_attendance_manager': True,
        })

        cls.other_subordinate_emp = cls._create_employee({
            'name': 'Other Subordinate',
            'parent_id': cls.other_mgr_emp.id,
        })

        cls.unassigned_emp = cls._create_employee({
            'name': 'Unassigned Employee',
            'parent_id': False,
        })

        # Dates for approval sheets
        cls.date_from = date(2026, 9, 1)
        cls.date_to = date(2026, 9, 30)

        # Helper method to create sheets
        cls.Sheet = cls.env['attendance.ot.approval.sheet']

    def _create_sheet(self, employee, state='submitted'):
        return self.Sheet.create({
            'employee_id': employee.id,
            'date_from': self.date_from,
            'date_to': self.date_to,
            'period_type': 'custom',
            'state': state,
        })

    def test_01_direct_manager_hierarchy(self):
        """Test direct manager sees and can approve direct reports only."""
        # 1. Subordinate hierarchy check
        sub_ids = self.middle_mgr_emp._get_subordinate_hierarchy_ids()
        self.assertIn(self.subordinate_1_emp.id, sub_ids)
        self.assertIn(self.subordinate_2_emp.id, sub_ids)
        self.assertNotIn(self.top_mgr_emp.id, sub_ids)
        self.assertNotIn(self.other_subordinate_emp.id, sub_ids)
        self.assertNotIn(self.unassigned_emp.id, sub_ids)

        # 2. Middle manager approves direct report
        sheet = self._create_sheet(self.subordinate_1_emp)
        sheet.with_user(self.middle_mgr_user).action_approve()
        self.assertEqual(sheet.state, 'approved')
        self.assertEqual(sheet.approved_by_id, self.middle_mgr_user)

    def test_02_manager_of_managers_full_subtree(self):
        """Test manager of managers sees direct reports + indirect reports in full subtree."""
        sub_ids = self.top_mgr_emp._get_subordinate_hierarchy_ids()
        self.assertIn(self.middle_mgr_emp.id, sub_ids, "Top manager must see direct report")
        self.assertIn(self.subordinate_1_emp.id, sub_ids, "Top manager must see indirect report 1")
        self.assertIn(self.subordinate_2_emp.id, sub_ids, "Top manager must see indirect report 2")
        self.assertNotIn(self.other_subordinate_emp.id, sub_ids, "Must not see other teams")
        self.assertNotIn(self.unassigned_emp.id, sub_ids, "Must not see unassigned")

        # Top manager approves indirect report
        sheet = self._create_sheet(self.subordinate_2_emp)
        sheet.with_user(self.top_mgr_user).action_approve()
        self.assertEqual(sheet.state, 'approved')
        self.assertEqual(sheet.approved_by_id, self.top_mgr_user)

        # Top manager approves direct report
        mgr_sheet = self._create_sheet(self.middle_mgr_emp)
        mgr_sheet.with_user(self.top_mgr_user).action_approve()
        self.assertEqual(mgr_sheet.state, 'approved')

    def test_03_unassigned_employee_restrictions(self):
        """Test unassigned employee cannot be approved by any regular manager, only HR admin."""
        sheet = self._create_sheet(self.unassigned_emp)

        # Direct manager attempt: blocked by record rule
        with self.assertRaises(AccessError):
            sheet.with_user(self.middle_mgr_user).action_approve()

        # Direct manager attempt bypassing record rule: blocked by server-side permission check
        with self.assertRaises(UserError) as cm:
            sheet.with_user(self.middle_mgr_user).sudo().action_approve()
        self.assertIn("not assigned to any manager", str(cm.exception))

        # Top manager attempt: blocked by record rule
        with self.assertRaises(AccessError):
            sheet.with_user(self.top_mgr_user).action_approve()

        # Top manager attempt bypassing record rule: blocked by server-side permission check
        with self.assertRaises(UserError) as cm:
            sheet.with_user(self.top_mgr_user).sudo().action_approve()
        self.assertIn("not assigned to any manager", str(cm.exception))

        # HR Admin attempt -> succeeds
        sheet.with_user(self.hr_admin_user).action_approve()
        self.assertEqual(sheet.state, 'approved')
        self.assertEqual(sheet.approved_by_id, self.hr_admin_user)

    def test_04_cross_team_access_blocked(self):
        """Test manager from team A cannot approve subordinate from team B."""
        sheet_team_b = self._create_sheet(self.other_subordinate_emp)

        # Blocked by record rule
        with self.assertRaises(AccessError):
            sheet_team_b.with_user(self.middle_mgr_user).action_approve()

        # Blocked by server-side hierarchy check if record rule bypassed
        with self.assertRaises(UserError) as cm:
            sheet_team_b.with_user(self.middle_mgr_user).sudo().action_approve()
        self.assertIn("Access Denied", str(cm.exception))

        sheet_team_a = self._create_sheet(self.subordinate_1_emp)
        # Blocked by record rule
        with self.assertRaises(AccessError):
            sheet_team_a.with_user(self.other_mgr_user).action_approve()

        # Blocked by server-side hierarchy check if record rule bypassed
        with self.assertRaises(UserError) as cm:
            sheet_team_a.with_user(self.other_mgr_user).sudo().action_approve()
        self.assertIn("Access Denied", str(cm.exception))

    def test_05_self_approval_blocked(self):
        """Test users cannot approve their own attendance sheets."""
        # Middle manager sheet approved by middle manager -> blocked
        mgr_sheet = self._create_sheet(self.middle_mgr_emp)
        with self.assertRaises(UserError) as cm:
            mgr_sheet.with_user(self.middle_mgr_user).action_approve()
        self.assertIn("cannot approve, reject, or adjust your own", str(cm.exception))

        # Top director sheet approved by top director -> blocked
        top_sheet = self._create_sheet(self.top_mgr_emp)
        with self.assertRaises(UserError) as cm:
            top_sheet.with_user(self.top_mgr_user).action_approve()
        self.assertIn("cannot approve, reject, or adjust your own", str(cm.exception))

    def test_06_circular_hierarchy_protection(self):
        """Test circular manager hierarchies do not cause recursion errors and get safely resolved."""
        # Create circular reference: EmpA -> EmpB -> EmpA
        emp_a = self._create_employee({'name': 'Circular A'})
        emp_b = self._create_employee({'name': 'Circular B', 'parent_id': emp_a.id})
        emp_a.parent_id = emp_b.id

        # Method should return cleanly without RecursionError / infinite loop
        sub_ids = emp_a._get_subordinate_hierarchy_ids()
        self.assertIn(emp_b.id, sub_ids)
        self.assertNotIn(emp_a.id, sub_ids)

        # Single node cycle: EmpC -> EmpC
        emp_c = self._create_employee({'name': 'Self Loop C'})
        emp_c.parent_id = emp_c.id
        sub_c = emp_c._get_subordinate_hierarchy_ids()
        self.assertNotIn(emp_c.id, sub_c)

        # Run fix utility
        fixed = self.env['hr.employee'].fix_circular_manager_hierarchies()
        self.assertTrue(len(fixed) > 0)
        self.assertFalse(emp_a.parent_id and emp_b.parent_id and emp_a.parent_id.id == emp_b.id and emp_b.parent_id.id == emp_a.id)

    def test_07_batch_approval_scoping(self):
        """Test batch approval respects reporting scope."""
        sheet_sub1 = self._create_sheet(self.subordinate_1_emp)
        sheet_sub2 = self._create_sheet(self.subordinate_2_emp)

        sheets = sheet_sub1 | sheet_sub2
        count = sheets.with_user(self.middle_mgr_user).action_batch_approve()
        self.assertEqual(count, 2)
        self.assertEqual(sheet_sub1.state, 'approved')
        self.assertEqual(sheet_sub2.state, 'approved')

    def test_08_record_rules_portal_manager_scoping(self):
        """Test ORM search by manager returns only subordinate sheets."""
        s1 = self._create_sheet(self.subordinate_1_emp)
        s_other = self._create_sheet(self.other_subordinate_emp)
        s_unassigned = self._create_sheet(self.unassigned_emp)

        # Search as Middle Manager
        mgr_sheets = self.Sheet.with_user(self.middle_mgr_user).search([
            ('id', 'in', [s1.id, s_other.id, s_unassigned.id])
        ])

        self.assertIn(s1, mgr_sheets, "Manager must be able to view subordinates' sheets")
        self.assertNotIn(s_other, mgr_sheets, "Manager must NOT see other teams' sheets")
        self.assertNotIn(s_unassigned, mgr_sheets, "Manager must NOT see unassigned employees' sheets")

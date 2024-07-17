from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field


def get_group_field(name):
    return FollowUpGroup._meta.get_field(name)


GroupsTable = MetabaseTable(name="gps_groups_v1")
GroupsTable.add_columns(
    [
        get_column_from_field(get_group_field("id"), "id"),
        get_column_from_field(get_group_field("created_at"), "created_at"),
        get_column_from_field(get_group_field("updated_at"), "updated_at"),
        get_column_from_field(get_group_field("created_in_bulk"), "created_in_bulk"),
        {
            "name": "department",
            "type": "text",
            "comment": "Département du bénéficiaire",
            "fn": lambda o: o.beneficiary_department,
        },
    ]
)


def get_membership_field(name):
    return FollowUpGroupMembership._meta.get_field(name)


MembershipsTable = MetabaseTable(name="gps_membres_v1")
MembershipsTable.add_columns(
    [
        get_column_from_field(get_membership_field("id"), "id"),
        get_column_from_field(get_membership_field("follow_up_group_id"), "group_id"),
        get_column_from_field(get_membership_field("created_at"), "created_at"),
        get_column_from_field(get_membership_field("updated_at"), "updated_at"),
        get_column_from_field(get_membership_field("ended_at"), "ended_at"),
        get_column_from_field(get_membership_field("is_referent"), "is_referent"),
        get_column_from_field(get_membership_field("member_id"), "member_id"),
        {
            "name": "org_departments",
            "type": "text[]",
            "comment": "Départements de l'organisation",
            "fn": lambda o: o.companies_departments or o.prescriber_departments,
        },
        get_column_from_field(get_membership_field("created_in_bulk"), "created_in_bulk"),
    ]
)

from itou.gps.models import FollowUpGroup, FollowUpGroupMembership
from itou.metabase.tables.utils import MetabaseTable, get_column_from_field, get_model_field


GroupsTable = MetabaseTable(name="gps_groups_v1")
GroupsTable.add_columns(
    [
        get_column_from_field(get_model_field(FollowUpGroup, "id"), "id"),
        get_column_from_field(get_model_field(FollowUpGroup, "created_at"), "created_at"),
        get_column_from_field(get_model_field(FollowUpGroup, "updated_at"), "updated_at"),
        get_column_from_field(get_model_field(FollowUpGroup, "created_in_bulk"), "created_in_bulk"),
        {
            "name": "department",
            "type": "text",
            "comment": "Département du bénéficiaire",
            "fn": lambda o: o.beneficiary_department,
        },
    ]
)


MembershipsTable = MetabaseTable(name="gps_membres_v1")
MembershipsTable.add_columns(
    [
        get_column_from_field(get_model_field(FollowUpGroupMembership, "id"), "id"),
        get_column_from_field(get_model_field(FollowUpGroupMembership, "follow_up_group_id"), "group_id"),
        get_column_from_field(get_model_field(FollowUpGroupMembership, "created_at"), "created_at"),
        get_column_from_field(get_model_field(FollowUpGroupMembership, "updated_at"), "updated_at"),
        get_column_from_field(get_model_field(FollowUpGroupMembership, "ended_at"), "ended_at"),
        get_column_from_field(get_model_field(FollowUpGroupMembership, "is_referent"), "is_referent"),
        get_column_from_field(get_model_field(FollowUpGroupMembership, "member_id"), "member_id"),
        {
            "name": "org_departments",
            "type": "text[]",
            "comment": "Départements de l'organisation",
            "fn": lambda o: o.companies_departments or o.prescriber_departments,
        },
        get_column_from_field(get_model_field(FollowUpGroupMembership, "created_in_bulk"), "created_in_bulk"),
    ]
)

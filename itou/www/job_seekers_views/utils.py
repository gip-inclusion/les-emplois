def get_organization_of_type(request, clazz):
    if isinstance(request.current_organization, clazz):
        return request.current_organization
    return None

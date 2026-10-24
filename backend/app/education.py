"""Read structured subjects without rewriting legacy education records."""
def subjects(data, field):
    key=field+'s'
    values=data[key] if key in data else [data.get(field,'')]
    result=[];seen=set()
    for value in values:
        value=value.strip()
        if value and value.casefold() not in seen:
            result.append(value);seen.add(value.casefold())
    return result

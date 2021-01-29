# How to test the API via CLI

## Get a token for a user from its login/password.

Warning: this may fail if you use an email with special characters (e.g. `+`).

```
curl -H 'Accept: application/json; indent=4' -d "username=me@me.com&password=password" http://127.0.0.1:8080/api/token-auth/
```

## Use this token to get the siaes of the user.

```
curl -H 'Accept: application/json; indent=4' -H 'Authorization: Token 123456' http://127.0.0.1:8080/api/siaes/
```

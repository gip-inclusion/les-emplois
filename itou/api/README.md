# How to test the API via CLI

## Get a token for a user from its login/password.

Warning: you need to _URL escape_ any special character in the email and password (e.g. `+` becomes `%2B`).

```
curl -H 'Accept: application/json; indent=4' -d "username=me@me.com&password=password" http://127.0.0.1:8080/api/v1/token-auth/
```

## Use this token to get the siaes of the user.

```
curl -H 'Accept: application/json; indent=4' -H 'Authorization: Token 123456' http://127.0.0.1:8080/api/v1/siaes/
```

web: gunicorn itou.wsgi --log-file -
postdeploy: python ./manage.py collectstatic && python ./manage.py migrate

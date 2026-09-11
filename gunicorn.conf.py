import multiprocessing


# Clever M instances have 4 CPUs and 10 workers seemed OK
workers = multiprocessing.cpu_count() * 2 + 2

wsgi_app = "config.wsgi:application"

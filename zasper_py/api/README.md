TODO:
(r".*/", TrailingSlashHandler),
(r"api", APIVersionHandler),
(r"/(robots\.txt|favicon\.ico)", PublicStaticFileHandler),
(r"/metrics", PrometheusMetricsHandler),
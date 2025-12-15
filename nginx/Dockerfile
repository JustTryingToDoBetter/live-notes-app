FROM nginx:alpine

COPY default.conf /etc/nginx/conf.d/default.conf

# Create the directory structure
WORKDIR /var/www/public

# Create a dummy index.php so Nginx try_files passes it to FPM
# (FPM has the real file)
RUN echo "<?php // silence is golden" > index.php

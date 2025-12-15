# We start from an official PHP image with FPM
# FPM is a FastCGI process manager, ideal behind Nginx
FROM php:8.3-fpm

# Install system dependencies Laravel commonly needs
RUN apt-get update && apt-get install -y \
    git \
    unzip \
    libpng-dev \
    libonig-dev \
    libxml2-dev \
    libzip-dev \
    zip \
    curl \
    && docker-php-ext-install \
        pdo \
        pdo_mysql \
        mbstring \
        zip \
        exif \
        pcntl \
        bcmath \
    && pecl install redis \
    && docker-php-ext-enable redis

# Set the working directory inside the container
WORKDIR /var/www

# Copy composer files first (better layer caching)
COPY composer.json composer.lock ./

# Install PHP dependencies inside the container
RUN curl -sS https://getcomposer.org/installer | php \
    && mv composer.phar /usr/local/bin/composer \
    && composer install --no-dev --no-interaction --prefer-dist

# Copy the rest of the Laravel application
COPY . .

# Fix permissions for Laravel storage & cache
RUN chown -R www-data:www-data storage bootstrap/cache

# Expose the PHP-FPM port
EXPOSE 9000

# Start PHP-FPM
CMD ["php-fpm"]

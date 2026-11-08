FROM nginx:1.27-alpine
RUN apk add --no-cache openssl tzdata \
 && rm -f /etc/nginx/conf.d/default.conf
COPY nginx.conf /etc/nginx/nginx.conf
COPY site.conf.template /etc/nginx/templates/site.conf.template
COPY 10-certificado.sh /docker-entrypoint.d/10-certificado.sh
RUN chmod 0755 /docker-entrypoint.d/10-certificado.sh
EXPOSE 80 443

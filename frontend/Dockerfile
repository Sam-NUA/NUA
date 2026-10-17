# Nua Frontend — React (Vite) served by nginx.
# REACT_APP_BACKEND_URL is baked at BUILD time (Vite replaces it in the bundle),
# so it must be passed via --build-arg or fly.toml's [build.args].
FROM node:22-alpine AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG REACT_APP_BACKEND_URL
ENV REACT_APP_BACKEND_URL=${REACT_APP_BACKEND_URL}
RUN npm run build

# ---------- runtime ----------
FROM nginx:alpine

# SPA-friendly nginx config — every unknown path falls through to /index.html.
# Written as a *template* under /etc/nginx/templates so the stock nginx
# entrypoint runs envsubst over it at boot and bakes in whatever $PORT the
# platform assigned (Railway assigns it dynamically). NGINX_ENVSUBST_FILTER
# pins substitution to PORT alone, so nginx's own $uri/$host stay untouched.
RUN mkdir -p /etc/nginx/templates \
 && printf '%s\n' \
    'server {' \
    '  listen ${PORT};' \
    '  root /usr/share/nginx/html;' \
    '  gzip on;' \
    '  gzip_types text/plain text/css application/javascript application/json image/svg+xml;' \
    '  location / {' \
    '    try_files $uri $uri/ /index.html;' \
    '  }' \
    '  location ~* \.(?:js|css|woff2?|ttf|png|jpg|jpeg|gif|svg|ico)$ {' \
    '    expires 30d;' \
    '    add_header Cache-Control "public, immutable";' \
    '  }' \
    '}' > /etc/nginx/templates/default.conf.template \
 && rm -f /etc/nginx/conf.d/default.conf

COPY --from=builder /app/build /usr/share/nginx/html

ENV PORT=8080 \
    NGINX_ENVSUBST_FILTER=^PORT$
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]

FROM node:20-alpine

WORKDIR /app/frontend

RUN apk add --no-cache wget

COPY frontend/package.json frontend/package-lock.json* ./
RUN npm install

COPY frontend /app/frontend

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0"]

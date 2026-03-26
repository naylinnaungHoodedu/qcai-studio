FROM node:24-alpine

WORKDIR /app

COPY apps/frontend/package*.json ./
RUN npm ci

COPY apps/frontend .

RUN npm run build

EXPOSE 3000

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]

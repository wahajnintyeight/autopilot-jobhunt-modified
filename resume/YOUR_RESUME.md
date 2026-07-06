# Muhammad Wahaj

**Email:** wahaj.dkz@gmail.com | **Phone:** +923244137276 | **LinkedIn:** linkedin.com/in/wahaj-5598 | **GitHub:** github.com/wahajnintyeight

---

## Summary

Full Stack Developer with 5+ years of experience building and shipping production-grade backend systems and client-facing web applications. Specialised in PHP/Laravel, Node.js/NestJS, and Go, with a strong track record in scalable API design, async pipelines, cloud infrastructure, and AI integrations. Comfortable owning the full lifecycle from architecture through deployment and ongoing optimisation.

---

## Experience

### Software Engineer (Full Stack) - Cynosure Designs Ltd.
**Lahore, Pakistan** | Feb 2023 - Mar 2026

- Owned full project lifecycle delivery of 5+ client web applications in a single year - from concept and technical design through to build, deployment, and ongoing refinement - using Laravel, Livewire, and ReactJS, without a dedicated PM or QA resource.
- Integrated Elasticsearch into a backend data service, reducing P95 load times by 40% for 1 million+ investor records and significantly improving search responsiveness.
- Built an asynchronous notification system using RabbitMQ, replacing a polling-based approach that reduced server load and delivered near-instant notifications.
- Collaborated closely with designers and project managers to deliver high-quality digital output on time and within budget.

### Software Developer - Azure Innovations
**Lahore, Pakistan** | Sep 2020 - Dec 2022

- Built and integrated REST APIs in Node.js backed by Redis caching to handle high-frequency transaction lookups, maintaining response times under 100ms during peak load.
- Automated CI/CD pipeline using AWS CodePipeline and CodeDeploy, reducing deployment time from 45 minutes to 12 minutes with automated rollback on failure.
- Designed and built a GPS tracking service in Go, handling concurrent location data streams from multiple devices, routing hot data to Redis, time-series writes to PostgreSQL, and raw event logs to MongoDB.

---

## Skills

**Languages:** PHP, JavaScript, TypeScript, Go/Golang, Python, SQL
**Backend and Frameworks:** Laravel, NestJS, Node.js, Express.js, Symfony
**Frontend:** ReactJS, Livewire, Tailwind CSS, HTML/CSS
**Databases:** PostgreSQL, MySQL, MongoDB, Redis, Elasticsearch
**Cloud and DevOps:** AWS (Lambda, SQS, SNS, S3, RDS, CodePipeline, CodeDeploy), GCP, Azure, Docker, Kubernetes, RabbitMQ, Linux, Git, CI/CD
**AI and Integrations:** Deepgram, Google MedLM, Gemini AI, OpenAI SDK, pgvector, RAG pipelines

---

## Education

**Bachelor of Science in Computer Science** - University of Central Punjab, Lahore, Pakistan | 2017 - 2021

---

## Projects

### RingbaApi - Call Analytics Backend
High-throughput NestJS/TypeScript backend processing thousands of webhooks daily against a 2M+ record PostgreSQL database. Features delta-based ingestion, PostgreSQL advisory locking, 13 active cron jobs, SSE live dashboard updates, and a failed-webhook retry queue with exponential backoff. Private repo - architecture documentation available on request.

### Project Phoenix V2
Microservices-based geolocation tracking system written in Go. Multi-service architecture (API Gateway, Location Service, Socket Service) communicating via RabbitMQ and gRPC/protobuf. Full rewrite from Node.js for improved concurrency under high device load. Containerised with Docker Compose. [github.com/wahajnintyeight/project-phoenix-v2](https://github.com/wahajnintyeight/project-phoenix-v2)

### SightFlow - Real-Time Media Analysis Platform
WebSocket streaming system integrating Gemini AI for real-time audio and image analysis. Handles 50+ concurrent screen shares with server-side buffering, encoding, and S3 storage integration. Stack: ReactJS, Python, Laravel, AWS.

### Notix-AI - Medical Audio Transcription
Audio-to-text pipeline integrating Deepgram and Google MedLM, processing 1,000+ medical notes monthly with 95% transcription accuracy. Serverless jobs via AWS Lambda and SQS with automatic retry logic. Stack: ReactJS, Python, Laravel, MySQL, AWS.

### Team2Challenge - Multi-Tenant Sports Management Platform
Event-driven notification service using RabbitMQ with retry logic and dead-letter exchanges, cutting email delivery latency by 60% with 99.9% delivery rate. Optimised PostgreSQL queries and Redis caching improved API response times by 50% under high load. Stack: NestJS, TypeScript, PostgreSQL, RabbitMQ, AWS.
# Optional online review service

Build from the repository root:

```sh
docker build -f server/Dockerfile -t score-parts-ai .
```

Run behind an HTTPS reverse proxy. Provide `OPENAI_API_KEY`, `OPENAI_MODEL`, and `SCORE_PARTS_TRIAL_TOKENS` as secrets, and mount `/data` as a persistent volume for quota counts. The service has no public signup; the operator distributes unique random trial tokens to invited users. Never expose port 8000 directly on the public Internet without HTTPS and operational rate limiting.

The server does not write page images to disk. It sends the selected image to the configured model provider. Review provider retention terms and give trial users a clear disclosure before distributing tokens. Production deployment, model costs, and data retention arrangements belong to the operator; this repository contains no live service credentials or deployment.

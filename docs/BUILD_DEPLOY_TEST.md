# TuskerSquad Build, Deploy, Test Pipeline

This document describes the enhanced TuskerSquad pipeline that includes automatic building, deployment to ephemeral environments, automated testing, and runtime analysis.

## Pipeline Overview

The complete 13-agent pipeline now includes:

1. **Planner** - Analyzes PR scope and plans the review strategy
2. **Backend** - Tests API endpoints, latency, error rates, pricing logic
3. **Frontend** - Tests UI flows, form validation, accessibility, cart behavior
4. **Security** - Probes authentication, JWT validation, injection vectors, auth bypass
5. **SRE** - Load tests checkout endpoint, measures P95 latency and throughput
6. **Builder** - Builds application from PR source code in isolated environment
7. **Deployer** - Deploys built application to ephemeral Docker environment
8. **Tester** - Executes automated tests against deployed application
9. **Runtime Analyzer** - Analyzes runtime behavior, logs, and test results
10. **Log Inspector** - Reads structured logs from all microservices
11. **Correlator** - Correlates client-side findings with server-side log events
12. **Challenger** - Audits peer agent findings for false positives and environment variance
13. **QA Lead** - Synthesizes all findings into risk assessment and standup summary
14. **Judge** - Makes final deployment decision based on all evidence

## Build Phase (Builder Agent)

The Builder agent performs the following steps:

1. **Repository Cloning**: Clones the PR branch from Gitea to a temporary directory
2. **Build Configuration Detection**: Scans for build files (Dockerfile, package.json, requirements.txt, Makefile)
3. **Docker Build**: Builds the application using Docker if a Dockerfile is present
4. **Artifact Validation**: Verifies that build artifacts are created successfully

### Build Requirements

For successful builds, the repository must contain one of:
- `Dockerfile` - For containerized applications
- `package.json` - For Node.js applications
- `requirements.txt` or `pyproject.toml` - For Python applications
- `Makefile` - For custom build processes

### Build Outputs

- Docker image tagged as `pr-{pr_number}-build`
- Build success/failure status
- Build logs and error messages

## Deploy Phase (Deployer Agent)

The Deployer agent creates ephemeral environments for testing:

1. **Image Verification**: Checks that the Docker image exists and is valid
2. **Container Creation**: Runs the application in an isolated Docker container
3. **Network Configuration**: Connects to the `tuskersquad-net` Docker network
4. **Health Monitoring**: Waits for the application to become healthy
5. **URL Assignment**: Assigns a unique port for the ephemeral deployment

### Ephemeral Environment

- **Isolation**: Each PR gets its own container with unique naming
- **Networking**: Connected to the same network as other services for integration testing
- **Port Assignment**: Dynamic port allocation (8080 + PR number % 10)
- **Lifecycle**: Containers are cleaned up after the workflow completes

## Test Phase (Tester Agent)

The Tester agent runs comprehensive automated tests:

1. **Health Check**: Verifies the application is responding correctly
2. **API Testing**: Tests key endpoints for proper responses
3. **Performance Testing**: Measures response times and throughput
4. **Error Handling**: Tests error conditions and edge cases

### Test Categories

- **Health Tests**: `/health` endpoint availability
- **API Tests**: CRUD operations, authentication, validation
- **Performance Tests**: Response time measurements
- **Load Tests**: Basic concurrent request handling

### Test Results

- Pass/fail status for each test category
- Response time metrics
- Error rates and failure analysis

## Runtime Analysis Phase (Runtime Analyzer Agent)

The Runtime Analyzer examines the live application:

1. **Log Analysis**: Retrieves and analyzes container logs for errors and warnings
2. **Performance Correlation**: Correlates test results with runtime metrics
3. **Resource Monitoring**: Checks CPU, memory, and network usage
4. **Failure Pattern Detection**: Identifies common failure modes

### Analysis Outputs

- Log anomaly detection
- Performance bottleneck identification
- Resource usage patterns
- Runtime health assessment

## Integration with Code Review

The build, deploy, test, and runtime analysis phases work together with the traditional code review:

1. **Static Analysis First**: Code review agents run first to catch obvious issues
2. **Runtime Validation**: Build and deploy provide actual running code for testing
3. **Combined Decision**: Judge agent considers both static findings and runtime results
4. **Comprehensive Coverage**: Catches issues that static analysis might miss

## Configuration

### Environment Variables

```bash
# Build configuration
BUILD_TIMEOUT=600  # Build timeout in seconds

# Deploy configuration
DEPLOY_TIMEOUT=60   # Deploy timeout in seconds
HEALTH_CHECK_RETRIES=30  # Number of health check attempts

# Test configuration
TEST_TIMEOUT=300    # Test execution timeout in seconds
PERFORMANCE_SAMPLES=5  # Number of performance test samples
RESPONSE_TIME_THRESHOLD=1000  # Max acceptable response time (ms)
```

### Docker Requirements

- Docker daemon must be accessible
- `tuskersquad-net` network must exist
- Sufficient disk space for container images
- Port range 8080-8089 available for ephemeral deployments

## Troubleshooting

### Build Failures

- Check that repository contains valid build configuration
- Verify Docker daemon is running and accessible
- Check build logs for specific error messages

### Deploy Failures

- Ensure Docker network `tuskersquad-net` exists
- Check port availability in the 8080-8089 range
- Verify application health check endpoint exists

### Test Failures

- Check deployed application URL is accessible
- Verify API endpoints match expected patterns
- Review application logs for runtime errors

### Runtime Analysis Issues

- Ensure container logging is properly configured
- Check Docker stats collection permissions
- Verify log volume mounts are correct

## Demo Application Enhancements

The demo ShopFlow application has been enhanced with:

- **Search API**: `/products/search?q=query` for product search
- **Product Details**: `/products/{id}` for individual product retrieval
- **Recommendations**: `/products/recommendations` for personalized suggestions
- **User Profiles**: `/user/profile` and `/user/orders` for user management
- **Health Checks**: `/health` endpoint for service monitoring

These endpoints provide more comprehensive testing scenarios for the automated pipeline.
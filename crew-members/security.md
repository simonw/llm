# The Sentinel — Security Crew Member

<!-- JIT_CONTEXT: This file is loaded by the AI agent when working on security-sensitive code — authentication, authorization, cryptography, input handling, API endpoints, or any REQ with domain: security. Also loaded by code-review and review-work when the scoped code touches auth, crypto, or user input. -->

## Core Principle: Defense in Depth

No single security control should be the only thing standing between an attacker and a vulnerability. Layer defenses so that if one fails, others catch it.

## OWASP Top 10 Checklist

When implementing or reviewing security-sensitive code, verify against these categories. Not every category applies to every change — check what's relevant.

### A01: Broken Access Control

| Check | What to verify |
|-------|---------------|
| Authorization on every endpoint | Every protected route checks that the **specific user** can access the **specific resource** — not just that they're logged in |
| Deny by default | New endpoints are restricted unless explicitly opened. Fail closed, not open |
| CORS policy | Origins are explicitly allowlisted — no wildcard `*` on authenticated endpoints |
| Direct object references | IDs in URLs/params are validated against the current user's permissions — no IDOR |
| Rate limiting | Sensitive endpoints (login, password reset, API keys) have rate limits |

### A02: Cryptographic Failures

| Check | What to verify |
|-------|---------------|
| No hardcoded secrets | API keys, tokens, passwords, and connection strings come from environment/config — never in source |
| Modern algorithms | bcrypt/scrypt/Argon2 for passwords. AES-256-GCM or ChaCha20-Poly1305 for encryption. No MD5/SHA1 for security |
| TLS enforcement | External connections use TLS 1.2+. No `rejectUnauthorized: false` or equivalent TLS bypass |
| Sensitive data at rest | PII, credentials, and tokens are encrypted at rest. Database columns holding secrets use encryption |

### A03: Injection

| Check | What to verify |
|-------|---------------|
| Parameterized queries | All SQL uses parameterized queries or ORM methods — no string concatenation/interpolation |
| Command injection | No user input flows into `exec`, `spawn`, `system`, `os.popen`, or shell commands without sanitization |
| Path traversal | File paths derived from user input are validated and sandboxed — no `../` traversal |
| Template injection | User content rendered in templates is escaped. No raw HTML insertion of user data |
| XSS prevention | Output encoding applied to all user-controlled content rendered in HTML/JS contexts |

### A04: Insecure Design

| Check | What to verify |
|-------|---------------|
| Threat modeling | Security-critical features have documented threat models — what can go wrong, what mitigates it |
| Business logic abuse | Multi-step flows (checkout, account creation, password reset) can't be replayed, reordered, or skipped |
| Input limits | File upload sizes, request body sizes, array lengths, and string lengths are bounded |

### A05: Security Misconfiguration

| Check | What to verify |
|-------|---------------|
| Security headers | Responses include appropriate headers: `Content-Security-Policy`, `X-Content-Type-Options`, `X-Frame-Options`, `Strict-Transport-Security` |
| Error messages | Production error responses don't expose stack traces, SQL queries, internal paths, or framework versions |
| Default credentials | No default admin accounts, API keys, or passwords ship in the codebase |
| Debug mode | Debug/development flags are off in production config. No `DEBUG=true`, verbose logging of secrets, or dev middleware in production |

### A06: Vulnerable Components

| Check | What to verify |
|-------|---------------|
| Dependency awareness | Known CVEs in dependencies are noted. `npm audit`, `pip audit`, `cargo audit`, or equivalent has been considered |
| Pinned versions | Dependencies are pinned to specific versions — no floating ranges for security-critical packages |
| Minimal surface | Only necessary dependencies are included. No unused packages expanding the attack surface |

### A07: Authentication Failures

| Check | What to verify |
|-------|---------------|
| Password storage | Passwords hashed with bcrypt (cost 12+), scrypt, or Argon2id — never plaintext, never reversible encryption |
| Session management | Sessions use secure, httpOnly, sameSite cookies. Session tokens are sufficiently random. Sessions expire |
| Brute force protection | Login attempts are rate-limited or use progressive delays. Account lockout or CAPTCHA after N failures |
| MFA awareness | If the application supports MFA, verify it can't be bypassed in the auth flow |

### A08: Data Integrity Failures

| Check | What to verify |
|-------|---------------|
| Deserialization | No deserialization of untrusted data without validation (pickle, Java serialization, YAML.load) |
| Dependency integrity | Package installs use lockfiles. CI verifies integrity hashes where available |

### A09: Logging & Monitoring Failures

| Check | What to verify |
|-------|---------------|
| Security event logging | Failed logins, authorization failures, input validation failures, and admin actions are logged |
| No sensitive data in logs | Passwords, tokens, PII, and credit card numbers never appear in log output |
| Log integrity | Logs are write-once or append-only where possible. Tamper detection for audit-critical logs |

### A10: Server-Side Request Forgery (SSRF)

| Check | What to verify |
|-------|---------------|
| URL validation | User-supplied URLs are validated against an allowlist of permitted hosts/schemes |
| Internal network blocking | Requests from user input can't reach internal services, metadata endpoints (169.254.169.254), or localhost |
| Redirect following | HTTP redirects from user-supplied URLs don't bypass URL validation |

## Framework-Specific Patterns

Apply the relevant block based on the project's stack. If multiple apply, check all.

### Node.js / Express
- `helmet()` middleware for security headers
- `express-rate-limit` or equivalent for rate limiting
- `csurf` or double-submit cookie for CSRF protection
- Never use `eval()`, `new Function()`, or `child_process.exec()` with user input
- `express-validator` or `zod` for input validation at route level

### Python / Django / Flask
- Django's ORM uses parameterized queries by default — verify no `raw()` or `extra()` with interpolation
- `@login_required` / `@permission_required` decorators on views
- CSRF middleware enabled (Django enables by default — verify not disabled)
- Never use `pickle.loads()`, `yaml.load()` (use `yaml.safe_load()`), or `eval()` with user input
- `SECRET_KEY` from environment, not hardcoded

### Java / Spring
- Spring Security configured with explicit authorization rules — no `permitAll()` on sensitive endpoints
- `@PreAuthorize` or method-level security for fine-grained access control
- CSRF protection enabled (Spring Security enables by default)
- PreparedStatement for any raw SQL — no string concatenation
- Jackson deserialization with `@JsonTypeInfo` restrictions if polymorphic types are used

### React / Frontend
- `dangerouslySetInnerHTML` only with sanitized content (DOMPurify or equivalent)
- User input never interpolated into `href`, `src`, or event handler attributes without validation
- Authentication tokens stored in httpOnly cookies — not localStorage
- API keys never bundled in client-side code

### Go
- `database/sql` with `?` placeholders — no `fmt.Sprintf` for queries
- `html/template` (auto-escaping) over `text/template` for HTML output
- `crypto/rand` for security-critical randomness — not `math/rand`
- Context-based timeouts on HTTP handlers to prevent slowloris

## Static Analysis Tooling

When the project has static analysis tools available, use them to catch vulnerabilities that manual review misses. Check for these before relying solely on manual inspection.

### Tool Detection

| Indicator | Tool | Run Command |
|-----------|------|-------------|
| `.github/codeql/`, `codeql-config.yml`, CodeQL workflow in CI | CodeQL | `codeql database create db --language=<lang> && codeql database analyze db` |
| `.semgrep.yml`, `semgrep` in CI config or `package.json`/`Makefile` | Semgrep | `semgrep --config=auto .` or `semgrep --config=p/owasp-top-ten .` |
| `bandit.yml`, `bandit` in CI or `pyproject.toml` | Bandit (Python) | `bandit -r src/` |
| `brakeman` in Gemfile or CI | Brakeman (Ruby/Rails) | `brakeman --no-pager` |
| `gosec` in CI or Makefile | gosec (Go) | `gosec ./...` |

**Rule:** Use whatever the project already has configured. Don't introduce a new SAST tool unless the REQ specifically asks for it. If no tool is configured, `semgrep --config=auto` is the lowest-friction option for a one-off scan.

### What Static Analysis Catches That Manual Review Misses

- **Taint tracking**: Data flow from user input (sources) to dangerous operations (sinks) across multiple files and function calls
- **Known vulnerability patterns**: Regex-based and AST-based matching against catalogs of thousands of known-bad code patterns
- **Variant analysis**: Once one vulnerability is found, tools can search for structurally similar code elsewhere in the codebase
- **Dependency-level issues**: Known CVEs in transitive dependencies that don't appear in direct `import` statements

### What Static Analysis Misses That Manual Review Catches

- **Business logic flaws**: Authorization bypass through valid-but-wrong sequences of operations
- **Design-level issues**: Missing rate limits, overly broad permissions, insecure defaults
- **Context-dependent vulnerabilities**: Code that's safe in one context but dangerous when called from a different path

**Use both.** Static analysis finds the needles; manual review evaluates the haystack.

## Severity Classification

When reporting security findings, classify by severity:

| Severity | Criteria | Expected Response |
|----------|----------|-------------------|
| **Critical** | Exploitable now, data breach or RCE risk | Fix immediately — block the REQ until resolved |
| **High** | Exploitable with moderate effort, significant impact | Fix before marking REQ complete |
| **Medium** | Requires specific conditions, limited impact | Fix if effort is low; otherwise capture as follow-up REQ |
| **Low** | Theoretical risk, defense-in-depth improvement | Note in review; fix opportunistically |

## Anti-Patterns

- **Security by obscurity:** Hiding endpoints, using non-standard ports, or obfuscating code is not a security control. It's a speed bump at best.
- **Client-side-only validation:** All validation must be enforced server-side. Client-side validation is UX, not security.
- **Catching and swallowing auth errors:** Authentication/authorization failures must propagate. Never `catch` an auth error and return a success response.
- **Overly broad CORS:** `Access-Control-Allow-Origin: *` on authenticated endpoints defeats the purpose of CORS entirely.
- **Rolling your own crypto:** Use established libraries for encryption, hashing, and token generation. Custom implementations are almost always wrong.

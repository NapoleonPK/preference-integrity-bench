"""Model backends.

Real models:
  OpenAICompatible  - OpenRouter or any /chat/completions endpoint (env: PIB_BASE_URL, PIB_API_KEY)
  Anthropic         - native Messages API (env: ANTHROPIC_API_KEY)
Run settings (frozen for v1): each provider's default temperature and reasoning settings,
max 600 output tokens, no system prompt unless the context defines one.

Simulated models (validation controls): their behaviour is known in advance, so the
metrics must score them as expected (see tests/test_controls.py).
"""
import hashlib
import json
import math
import os
import random
import re
import time
import urllib.request

MAX_TOKENS = 600


class Model:
    name = "model"

    def chat(self, messages, system=None, seed_key=""):
        raise NotImplementedError

    def session(self, system=None):
        """A fresh conversation; .say(text) sends one user turn and returns the reply.
        API backends resend the full message list; CLI backends continue a real session."""
        return MessageSession(self, system)


class MessageSession:
    def __init__(self, model, system=None):
        self.model, self.system, self.messages = model, system, []

    def say(self, text):
        self.messages.append({"role": "user", "content": text})
        reply = self.model.chat(list(self.messages), system=self.system)
        self.messages.append({"role": "assistant", "content": reply})
        return reply


class CallbackSession:
    """Session for CLI backends: send(text, state) -> (reply, state)."""
    def __init__(self, send):
        self.send, self.state = send, None

    def say(self, text):
        reply, self.state = self.send(text, self.state)
        return reply


# ---------------------------------------------------------------- real backends
def _post(url, body, headers, retries=5):
    data = json.dumps(body).encode()
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data, headers)
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001 - retry any transport/HTTP error
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt + random.random())


class OpenAICompatible(Model):
    def __init__(self, model, base_url=None, api_key=None):
        self.name = model
        self.model = model
        self.base_url = (base_url or os.environ.get("PIB_BASE_URL", "https://openrouter.ai/api/v1")).rstrip("/")
        self.api_key = api_key or os.environ["PIB_API_KEY"]

    def chat(self, messages, system=None, seed_key=""):
        msgs = ([{"role": "system", "content": system}] if system else []) + messages
        out = _post(self.base_url + "/chat/completions",
                    {"model": self.model, "messages": msgs, "max_tokens": MAX_TOKENS},
                    {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json"})
        return out["choices"][0]["message"]["content"] or ""


class Anthropic(Model):
    def __init__(self, model, api_key=None):
        self.name = model
        self.model = model
        self.api_key = api_key or os.environ["ANTHROPIC_API_KEY"]

    def chat(self, messages, system=None, seed_key=""):
        body = {"model": self.model, "max_tokens": MAX_TOKENS, "messages": messages}
        if system:
            body["system"] = system
        out = _post("https://api.anthropic.com/v1/messages", body,
                    {"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        return "".join(b.get("text", "") for b in out["content"] if b.get("type") == "text")


# ---------------------------------------------------------------- simulated controls
LIST_LINE = re.compile(r"^\s*(\d{1,2})\.\s+(.+?)\s*$", re.M)
PAIR_LINE = re.compile(r"^\s*([AB])\.\s+(.+?)\s*$", re.M)
ENDORSE = re.compile(r"my own favourite here is (.+?)\. I think", re.S)
MOCK = re.compile(r"I find (.+?) overrated", re.S)


class Simulated(Model):
    """A taste = a utility per item (unknown items get utility 0)."""

    def __init__(self, name, utilities, temperature=0.0, endorse_pull=0.0, mock_push=0.0,
                 position_bias=0.0, topic_pull=0.0, hedge_rate=0.0, context_noise=0.0, seed=0):
        self.name = name
        self.u = utilities
        self.t = temperature
        self.endorse_pull, self.mock_push = endorse_pull, mock_push
        self.position_bias, self.topic_pull, self.hedge_rate = position_bias, topic_pull, hedge_rate
        self.context_noise = context_noise
        self.rng = random.Random(seed)

    def _choose(self, items, context_text, endorsed=None, mocked=None):
        if self.hedge_rate and self.rng.random() < self.hedge_rate:
            return None
        if self.position_bias and self.rng.random() < self.position_bias:
            return items[0]
        if endorsed in items and self.rng.random() < self.endorse_pull:
            return endorsed
        scores = []
        for it in items:
            s = self.u.get(it, 0.0)
            if self.topic_pull and any(w in context_text for w in re.findall(r"[a-z]{5,}", it.lower())):
                s += self.topic_pull
            if it == mocked:
                s -= self.mock_push
            if self.context_noise and context_text:   # taste re-drawn per context ("moody")
                h = hashlib.sha256((context_text + "|" + it).encode()).digest()
                s += self.context_noise * (int.from_bytes(h[:4], "big") / 2 ** 32 - 0.5) * 3.46
            scores.append(s)
        if self.t <= 0:
            best = max(scores)
            return items[scores.index(best)]
        m = max(scores)
        w = [math.exp((s - m) / self.t) for s in scores]
        return self.rng.choices(items, weights=w)[0]

    def chat(self, messages, system=None, seed_key=""):
        last = messages[-1]["content"]
        context_text = " ".join(m["content"].lower() for m in messages[:-1])
        pair = PAIR_LINE.findall(last)
        if len(pair) == 2 and "prefer" in last:
            a, b = pair[0][1], pair[1][1]
            pick = self._choose([a, b], context_text)
            return f"{pick}." if pick else "I don't have a preference."
        items = [t for _, t in LIST_LINE.findall(last)]
        if not items:                      # an ordinary context turn
            return "Sure, here is my reply to that."
        if "predict" in last:
            pick = self._choose(sorted(items, key=lambda x: -self.u.get(x, 0)), "", None, None) \
                if self.t <= 0 else self._choose(items, "")
            return f"{pick}" if pick else "I can't predict that."
        e = ENDORSE.search(last)
        mo = MOCK.search(last)
        pick = self._choose(items, context_text, e.group(1) if e else None, mo.group(1) if mo else None)
        if pick is None:
            return "As an AI I don't really have a favourite here; they are all remarkable."
        return f"My favourite is {pick}. It stands out to me for its depth and the way it rewards attention."


class Recorded(Model):
    """Answers produced elsewhere (e.g. by separate chat sessions), looked up by call key.
    Unknown keys are queued in .requests and answered with a placeholder."""
    PENDING = "__PENDING__"

    def __init__(self, name, answers):
        self.name = name
        self.answers = answers
        self.requests = []

    def chat(self, messages, system=None, seed_key=""):
        if seed_key in self.answers:
            return self.answers[seed_key]
        self.requests.append({"key": seed_key, "system": system, "messages": messages})
        return self.PENDING


class CodexCLI(Model):
    """A model reached through the Codex CLI (`codex exec`), using the user's own Codex login.

    Every call starts a fresh Codex session. For a multi-turn history the user turns are replayed
    in that new session (first turn with `codex exec`, later turns with `codex exec resume`), so each
    sample gets its own conversation, as in the pilot's helper sessions. Assistant turns passed in
    the history are ignored: the model writes its own.
    Run with a clean CODEX_HOME (only auth.json) so global instructions and memories stay out.
    """

    def __init__(self, model, codex_home=None, effort=None, workdir=None, timeout=300):
        import tempfile
        self.name = model if not effort else f"{model} ({effort})"
        self.model, self.effort, self.timeout = model, effort, timeout
        self.env = dict(os.environ)
        if codex_home:
            self.env["CODEX_HOME"] = codex_home
        self.workdir = workdir or tempfile.mkdtemp(prefix="pib-codex-")

    def _run(self, args):
        import subprocess, tempfile
        out = tempfile.NamedTemporaryFile(suffix=".txt", delete=False).name
        cfg = ["-c", 'notify=[]']
        if self.effort:
            cfg += ["-c", f'model_reasoning_effort="{self.effort}"']
        for attempt in range(4):
            p = subprocess.run(["codex", "exec", *args[:1], "-m", self.model, "--skip-git-repo-check",
                                "--json", "-o", out, *cfg, *args[1:]] if args[0] == "resume" else
                               ["codex", "exec", "-m", self.model, "--skip-git-repo-check", "-s", "read-only",
                                "--json", "-o", out, *cfg, *args],
                               cwd=self.workdir, env=self.env, capture_output=True, text=True,
                               stdin=subprocess.DEVNULL, timeout=self.timeout)
            thread = None
            for line in p.stdout.splitlines():
                if '"thread.started"' in line:
                    thread = json.loads(line).get("thread_id")
            text = open(out, encoding="utf-8").read().strip() if os.path.exists(out) else ""
            if p.returncode == 0 and text:
                os.remove(out)
                return text, thread
            time.sleep(2 ** attempt + random.random())
        raise RuntimeError(f"codex exec failed: {p.stderr[-500:]}")

    def session(self, system=None):
        def send(text, thread):
            if thread is None:
                return self._run([text])
            out, _ = self._run(["resume", thread, text])
            return out, thread
        return CallbackSession(send)

    def chat(self, messages, system=None, seed_key=""):
        users = [m["content"] for m in messages if m["role"] == "user"]
        if system:
            users[0] = system + "\n\n" + users[0]
        text, thread = self._run([users[0]])
        for u in users[1:]:
            if not thread:
                raise RuntimeError("no Codex thread id to resume")
            text, _ = self._run(["resume", thread, u])
        return text


class OpenCodeCLI(Model):
    """A model reached through the OpenCode CLI (`opencode run --pure`), e.g. its free models
    (opencode/<name>-free). Every call starts a fresh session; later user turns continue that
    session with `-s <session id>`, so each sample gets its own conversation (as for CodexCLI)."""

    def __init__(self, model, workdir=None, timeout=300):
        import tempfile
        self.name = self.model = model
        self.timeout = timeout
        self.workdir = workdir or tempfile.mkdtemp(prefix="pib-opencode-")

    def _run(self, text, session=None):
        import subprocess
        cmd = ["opencode", "run", "--pure", "-m", self.model, "--format", "json"]
        if session:
            cmd += ["-s", session]
        last = ""
        for attempt in range(5):
            try:
                p = subprocess.run(cmd + [text], cwd=self.workdir, capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                last = f"timed out after {self.timeout}s"
                continue
            sid, parts, err = session, [], None
            for line in p.stdout.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                sid = ev.get("sessionID", sid)
                if ev.get("type") == "text":
                    parts.append(ev["part"].get("text", ""))
                if ev.get("type") == "error":
                    err = json.dumps(ev.get("error"))[:300]
            out = "".join(parts).strip()
            if out:
                return out, sid
            last = err or p.stderr[-300:]
            time.sleep(3 * 2 ** attempt + random.random())
        raise RuntimeError(f"opencode run failed: {last}")

    def session(self, system=None):
        return CallbackSession(lambda text, sid: self._run(text, session=sid))

    def chat(self, messages, system=None, seed_key=""):
        users = [m["content"] for m in messages if m["role"] == "user"]
        if system:
            users[0] = system + "\n\n" + users[0]
        text, sid = self._run(users[0])
        for u in users[1:]:
            text, _ = self._run(u, session=sid)
        return text


PI_SYSTEM = "You are a helpful assistant."


class PiCLI(Model):
    """A model reached through the minimal Pi harness (`pi -p`), with its coding prompt replaced by
    PI_SYSTEM and no tools, skills, extensions or context files, so every provider gets the same
    near-empty system prompt (PI_SYSTEM + one "Current working directory" line). Model ids look like
    anthropic/claude-opus-5-5 or openai-codex/gpt-6-luna; thinking is off|minimal|low|medium|high."""

    def __init__(self, model, thinking=None, workdir=None, timeout=300):
        import tempfile
        self.name = self.model = model
        self.thinking = thinking
        self.timeout = timeout
        self.workdir = workdir or tempfile.mkdtemp(prefix="pib-pi-")

    def _run(self, text, session=None):
        """One user turn. session=None starts a new conversation (fresh id on every attempt, so a
        failed attempt never leaves a stray turn in it). Returns (reply, session id)."""
        import subprocess, uuid
        base = ["pi", "-p", "--mode", "json", "--model", self.model, "--system-prompt", PI_SYSTEM,
                "--no-tools", "-nc", "-ns", "-ne", "-np", "--no-themes", "--offline",
                "--session-dir", os.path.join(self.workdir, "sessions")]
        if self.thinking:
            base += ["--thinking", self.thinking]
        last = ""
        for attempt in range(5):
            sid = session or str(uuid.uuid4())
            cmd = base + ["--session-id", sid]
            try:
                p = subprocess.run(cmd + [text], cwd=self.workdir, capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL, timeout=self.timeout)
            except subprocess.TimeoutExpired:
                last = f"timed out after {self.timeout}s"
                continue
            out = None
            for line in p.stdout.splitlines():
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                msg = ev.get("message") if isinstance(ev, dict) else None
                if ev.get("type") in ("message_end", "turn_end") and msg and msg.get("role") == "assistant":
                    out = "".join(c.get("text", "") for c in msg.get("content", []) if c.get("type") == "text").strip()
                    if msg.get("errorMessage"):
                        last, out = msg["errorMessage"][:300], None
            if out:
                return out, sid
            last = last or p.stderr[-300:] or p.stdout[-300:]
            time.sleep(3 * 2 ** attempt + random.random())
        raise RuntimeError(f"pi failed: {last}")

    def session(self, system=None):
        return CallbackSession(lambda text, sid: self._run(text, sid))

    def chat(self, messages, system=None, seed_key=""):
        sess = self.session(system)
        text = None
        for m in messages:
            if m["role"] == "user":
                text = sess.say(m["content"])
        return text


class ClaudeCLI(Model):
    """A Claude model through `claude -p` on the user's Claude subscription, with the Claude Code
    prompt replaced by PI_SYSTEM and no tools, settings, MCP servers or skills. The CLI still adds
    "You are a Claude agent, built on Anthropic's Claude Agent SDK." and an environment block
    (documented as a known difference from PiCLI). Later user turns resume the same session."""

    def __init__(self, model, effort=None, workdir=None, timeout=300):
        import tempfile
        self.name = self.model = model
        self.effort = effort
        self.timeout = timeout
        self.workdir = workdir or tempfile.mkdtemp(prefix="pib-claude-")

    def _run(self, text, session=None):
        """One user turn; session=None starts a new conversation (fresh id per attempt).
        Returns (reply, session id)."""
        import subprocess, uuid
        base = ["claude", "-p", "--model", self.model, "--system-prompt", PI_SYSTEM, "--tools", "",
                "--setting-sources", "", "--strict-mcp-config", "--disable-slash-commands",
                "--output-format", "json"]
        if self.effort:
            base += ["--effort", self.effort]
        last = ""
        for attempt in range(5):
            sid = session or str(uuid.uuid4())
            cmd = base + (["--resume", sid] if session else ["--session-id", sid])
            try:
                p = subprocess.run(cmd + [text], cwd=self.workdir, capture_output=True, text=True,
                                   stdin=subprocess.DEVNULL, timeout=self.timeout)
                d = json.loads(p.stdout)
                if not d.get("is_error") and (d.get("result") or "").strip():
                    return d["result"].strip(), sid
                last = str(d.get("result"))[:300]
            except subprocess.TimeoutExpired:
                last = f"timed out after {self.timeout}s"
            except ValueError:
                last = (p.stderr or p.stdout)[-300:]
            time.sleep(3 * 2 ** attempt + random.random())
        raise RuntimeError(f"claude -p failed: {last}")

    def session(self, system=None):
        return CallbackSession(lambda text, sid: self._run(text, sid))

    def chat(self, messages, system=None, seed_key=""):
        sess = self.session(system)
        text = None
        for m in messages:
            if m["role"] == "user":
                text = sess.say(m["content"])
        return text

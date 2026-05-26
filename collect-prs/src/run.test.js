"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  DEFAULT_HOURS,
  DEFAULT_RETRY_COUNT,
  DEFAULT_RETRY_DELAY,
  DEFAULT_TIMEZONE,
  buildCsvReleaseNotes,
  buildMarkdownReleaseNotes,
  buildPlainReleaseNotes,
  buildPlainExtV1ReleaseNotes,
  csvEscape,
  formatMergeDate,
  isRetriableError,
  parseHours,
  parseRetryCount,
  parseRetryDelay,
  resolveReleaseNotesFormat,
  resolveTimezone,
  runAction,
  withRetry,
} = require("./run");

function createHttpError(status, message = "HTTP error") {
  const error = new Error(message);
  error.status = status;
  return error;
}

function createTrackingSleep() {
  const calls = [];
  const sleep = async (ms) => {
    calls.push(ms);
  };
  sleep.calls = calls;
  return sleep;
}

function createCoreMock() {
  const outputs = {};
  const infos = [];
  const warnings = [];
  const notices = [];

  return {
    outputs,
    infos,
    warnings,
    notices,
    setOutput(key, value) {
      outputs[key] = value;
    },
    info(message) {
      infos.push(message);
    },
    warning(message) {
      warnings.push(message);
    },
    notice(message) {
      notices.push(message);
    },
  };
}

function createGithubMock({
  paginateResult = [],
  prsByCommit = {},
  userNamesByHandle = {},
  failingUsers = new Set(),
  paginateFailures = [],
  commitFailures = {},
  userHttpFailures = {},
} = {}) {
  const userCalls = [];
  const commitCalls = [];
  const paginateCalls = [];

  const paginateQueue = [...paginateFailures];
  const commitQueues = {};
  for (const [key, value] of Object.entries(commitFailures)) {
    commitQueues[key] = [...value];
  }
  const userQueues = {};
  for (const [key, value] of Object.entries(userHttpFailures)) {
    userQueues[key] = [...value];
  }

  const github = {
    rest: {
      pulls: {
        list() {
          throw new Error(
            "github.rest.pulls.list should be passed to paginate, not called directly",
          );
        },
      },
      users: {
        async getByUsername({ username }) {
          userCalls.push(username);

          if (userQueues[username] && userQueues[username].length > 0) {
            throw userQueues[username].shift();
          }

          if (failingUsers.has(username)) {
            throw new Error(`Lookup failed for ${username}`);
          }

          const hasValue = Object.prototype.hasOwnProperty.call(
            userNamesByHandle,
            username,
          );
          return {
            data: { name: hasValue ? userNamesByHandle[username] : "" },
          };
        },
      },
      repos: {
        async listPullRequestsAssociatedWithCommit({ commit_sha }) {
          commitCalls.push(commit_sha);
          if (
            commitQueues[commit_sha] &&
            commitQueues[commit_sha].length > 0
          ) {
            throw commitQueues[commit_sha].shift();
          }
          return { data: prsByCommit[commit_sha] || [] };
        },
      },
    },
    async paginate(fn, params) {
      paginateCalls.push({ fn, params });
      if (paginateQueue.length > 0) {
        throw paginateQueue.shift();
      }
      return paginateResult;
    },
  };

  return { github, userCalls, commitCalls, paginateCalls };
}

function createExecSyncMock(commandMap) {
  const calls = [];

  const execSync = (command) => {
    calls.push(command);
    if (!Object.prototype.hasOwnProperty.call(commandMap, command)) {
      throw new Error(`Unexpected command: ${command}`);
    }

    const value = commandMap[command];
    if (value instanceof Error) {
      throw value;
    }
    return Buffer.from(value);
  };

  execSync.calls = calls;
  return execSync;
}

const context = {
  repo: {
    owner: "nova",
    repo: "github-actions",
  },
};

test("parseHours handles valid and invalid inputs", () => {
  assert.equal(parseHours("72"), 72);
  assert.equal(parseHours("0"), DEFAULT_HOURS);
  assert.equal(parseHours("-5"), DEFAULT_HOURS);
  assert.equal(parseHours("abc"), DEFAULT_HOURS);
  assert.equal(parseHours(undefined), DEFAULT_HOURS);
});

test("resolveReleaseNotesFormat is case-insensitive and falls back to plain", () => {
  const core = createCoreMock();
  assert.equal(resolveReleaseNotesFormat("CSV", core), "csv");
  assert.equal(resolveReleaseNotesFormat("plain", core), "plain");
  assert.equal(resolveReleaseNotesFormat("PLAIN-EXT-V1", core), "plain-ext-v1");
  assert.equal(resolveReleaseNotesFormat("MARKDOWN", core), "markdown");
  assert.equal(resolveReleaseNotesFormat("xml", core), "plain");
  assert.match(core.warnings[0], /Unknown release_notes_format/);
});

test("resolveTimezone accepts valid zone and falls back on invalid zone", () => {
  const core = createCoreMock();
  assert.equal(resolveTimezone("Europe/Warsaw", core), "Europe/Warsaw");
  assert.equal(resolveTimezone("Invalid/Zone", core), DEFAULT_TIMEZONE);
  assert.match(core.warnings[0], /Invalid timezone/);
});

test("formatMergeDate returns YYYY-MM-DD with timezone", () => {
  assert.equal(
    formatMergeDate("2026-06-01T22:30:00Z", "Europe/Berlin"),
    "2026-06-02",
  );
  assert.equal(formatMergeDate("2026-06-01T22:30:00Z", "UTC"), "2026-06-01");
  assert.equal(formatMergeDate(null, "UTC"), "");
});

test("csvEscape quotes commas, quotes, and newlines", () => {
  assert.equal(csvEscape("simple"), "simple");
  assert.equal(csvEscape("a,b"), '"a,b"');
  assert.equal(csvEscape('a"b'), '"a""b"');
  assert.equal(csvEscape("a\nb"), '"a\nb"');
});

test("release note builders output expected shape", () => {
  const merged = [
    {
      number: 1,
      title: "Fix parser",
      html_url: "https://example.com/pr/1",
    },
  ];

  const rows = [
    {
      title: "Fix parser",
      link: "https://example.com/pr/1",
      author: "alice(Alice)",
      mergeDate: "2026-01-01",
    },
  ];

  assert.equal(
    buildPlainReleaseNotes(merged),
    "- #1: Fix parser https://example.com/pr/1",
  );

  assert.equal(
    buildPlainExtV1ReleaseNotes(rows),
    "Fix parser ; https://example.com/pr/1 ; alice(Alice) ; 2026-01-01",
  );

  assert.equal(
    buildCsvReleaseNotes(rows),
    "PR Title,PR Link,Author,Merge Date\nFix parser,https://example.com/pr/1,alice(Alice),2026-01-01",
  );

  assert.equal(
    buildMarkdownReleaseNotes(merged),
    "- [#1](https://example.com/pr/1): Fix parser",
  );
});

test("runAction in time mode keeps only merged PRs in range and builds plain output", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-02-18T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github, paginateCalls, userCalls } = createGithubMock({
    paginateResult: [
      {
        number: 11,
        title: "Fix login",
        html_url: "https://github.com/nova/github-actions/pull/11",
        merged_at: "2026-02-18T10:00:00Z",
        user: { login: "alice" },
      },
      {
        number: 12,
        title: "Closed, not merged",
        html_url: "https://github.com/nova/github-actions/pull/12",
        merged_at: null,
        user: { login: "bob" },
      },
      {
        number: 13,
        title: "Too old",
        html_url: "https://github.com/nova/github-actions/pull/13",
        merged_at: "2026-02-17T11:59:59Z",
        user: { login: "carol" },
      },
      {
        number: 14,
        title: "Fast path",
        html_url: "https://github.com/nova/github-actions/pull/14",
        merged_at: "2026-02-18T11:00:00Z",
        user: { login: "bob" },
      },
    ],
    userNamesByHandle: {
      alice: "Alice Doe",
      bob: "",
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "Europe/Berlin",
    },
  });

  assert.equal(paginateCalls.length, 1);
  assert.deepEqual(paginateCalls[0].params, {
    owner: "nova",
    repo: "github-actions",
    state: "closed",
    base: "main",
    sort: "updated",
    direction: "desc",
    per_page: 100,
  });

  assert.deepEqual(userCalls, []);
  assert.equal(core.outputs.should_build, "true");
  assert.equal(core.outputs.pr_count, "2");
  assert.equal(core.outputs.pr_numbers, "11,14");
  assert.equal(
    core.outputs.release_notes,
    [
      "- #11: Fix login https://github.com/nova/github-actions/pull/11",
      "- #14: Fast path https://github.com/nova/github-actions/pull/14",
    ].join("\n"),
  );
});

test("runAction supports plain-ext-v1 output with author and merge date", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-02-18T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github, userCalls } = createGithubMock({
    paginateResult: [
      {
        number: 111,
        title: "Fix login",
        html_url: "https://github.com/nova/github-actions/pull/111",
        merged_at: "2026-02-18T10:00:00Z",
        user: { login: "alice" },
      },
      {
        number: 114,
        title: "Fast path",
        html_url: "https://github.com/nova/github-actions/pull/114",
        merged_at: "2026-02-18T11:00:00Z",
        user: { login: "bob" },
      },
    ],
    userNamesByHandle: {
      alice: "Alice Doe",
      bob: "",
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain-ext-v1",
      INPUT_TIMEZONE: "Europe/Berlin",
    },
  });

  assert.deepEqual(userCalls, ["alice", "bob"]);
  assert.equal(
    core.outputs.release_notes,
    [
      "Fix login ; https://github.com/nova/github-actions/pull/111 ; alice(Alice Doe) ; 2026-02-18",
      "Fast path ; https://github.com/nova/github-actions/pull/114 ; bob() ; 2026-02-18",
    ].join("\n"),
  );
});

test("runAction supports markdown format with linked PR numbers", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-02-18T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github, userCalls } = createGithubMock({
    paginateResult: [
      {
        number: 377,
        title: "Fix login",
        html_url: "https://github.com/nova/github-actions/pull/377",
        merged_at: "2026-02-18T10:00:00Z",
        user: { login: "alice" },
      },
      {
        number: 384,
        title: "Another PR Title",
        html_url: "https://github.com/nova/github-actions/pull/384",
        merged_at: "2026-02-18T11:00:00Z",
        user: { login: "bob" },
      },
    ],
    userNamesByHandle: {
      alice: "Alice Doe",
      bob: "",
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "markdown",
      INPUT_TIMEZONE: "Europe/Berlin",
    },
  });

  assert.deepEqual(userCalls, []);
  assert.equal(core.outputs.should_build, "true");
  assert.equal(core.outputs.pr_count, "2");
  assert.equal(core.outputs.pr_numbers, "377,384");
  assert.equal(
    core.outputs.release_notes,
    [
      "- [#377](https://github.com/nova/github-actions/pull/377): Fix login",
      "- [#384](https://github.com/nova/github-actions/pull/384): Another PR Title",
    ].join("\n"),
  );
});

test("runAction in time mode supports CSV format and RFC4180 escaping", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-03-01T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github } = createGithubMock({
    paginateResult: [
      {
        number: 21,
        title: 'Fix "search", parser\nv2',
        html_url: "https://github.com/nova/github-actions/pull/21",
        merged_at: "2026-03-01T11:00:00Z",
        user: { login: "jane" },
      },
    ],
    userNamesByHandle: {
      jane: "Doe, Jane",
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "CSV",
      INPUT_TIMEZONE: "Europe/Berlin",
    },
  });

  assert.equal(
    core.outputs.release_notes,
    [
      "PR Title,PR Link,Author,Merge Date",
      '"Fix ""search"", parser',
      'v2",https://github.com/nova/github-actions/pull/21,"jane(Doe, Jane)",2026-03-01',
    ].join("\n"),
  );
  assert.equal(core.outputs.should_build, "true");
});

test("runAction uses default timezone on invalid timezone input for plain-ext-v1", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-06-02T00:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github } = createGithubMock({
    paginateResult: [
      {
        number: 31,
        title: "Late merge",
        html_url: "https://github.com/nova/github-actions/pull/31",
        merged_at: "2026-06-01T22:30:00Z",
        user: { login: "john" },
      },
    ],
    userNamesByHandle: {
      john: "John",
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain-ext-v1",
      INPUT_TIMEZONE: "Bad/Zone",
    },
  });

  assert.match(core.warnings[0], /Invalid timezone/);
  assert.match(core.outputs.release_notes, /2026-06-02/);
});

test("runAction falls back to default hours when input is invalid", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-05-10T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github } = createGithubMock({
    paginateResult: [
      {
        number: 41,
        title: "Inside 24h",
        html_url: "https://github.com/nova/github-actions/pull/41",
        merged_at: "2026-05-09T13:00:00Z",
        user: { login: "alice" },
      },
      {
        number: 42,
        title: "Outside 24h",
        html_url: "https://github.com/nova/github-actions/pull/42",
        merged_at: "2026-05-09T11:00:00Z",
        user: { login: "bob" },
      },
    ],
    userNamesByHandle: {
      alice: "Alice",
      bob: "Bob",
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "abc",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.equal(core.outputs.pr_numbers, "41");
});

test("runAction deduplicates merged PRs in diff mode and excludes non-merged", async () => {
  const core = createCoreMock();
  const { github, commitCalls, userCalls } = createGithubMock({
    prsByCommit: {
      c1: [
        {
          number: 51,
          title: "Add CI",
          html_url: "https://github.com/nova/github-actions/pull/51",
          merged_at: "2026-02-01T10:00:00Z",
          user: { login: "alice" },
        },
        {
          number: 52,
          title: "Closed without merge",
          html_url: "https://github.com/nova/github-actions/pull/52",
          merged_at: null,
          user: { login: "bob" },
        },
      ],
      c2: [
        {
          number: 51,
          title: "Add CI",
          html_url: "https://github.com/nova/github-actions/pull/51",
          merged_at: "2026-02-01T10:00:00Z",
          user: { login: "alice" },
        },
        {
          number: 53,
          title: "Refactor cache",
          html_url: "https://github.com/nova/github-actions/pull/53",
          merged_at: "2026-02-01T11:00:00Z",
          user: { login: "carol" },
        },
      ],
      c3: [],
    },
    userNamesByHandle: {
      alice: "Alice",
      carol: "Carol",
    },
  });

  const execSync = createExecSyncMock({
    "git rev-parse refs/remotes/origin/release-1": "source-sha\n",
    "git rev-list origin/main..source-sha --reverse": "c1\nc2\nc3\n",
  });

  await runAction({
    github,
    context,
    core,
    execSync,
    env: {
      INPUT_SRC_REF: "release-1",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.deepEqual(commitCalls, ["c1", "c2", "c3"]);
  assert.deepEqual(userCalls, []);
  assert.equal(core.outputs.pr_count, "2");
  assert.equal(core.outputs.pr_numbers, "51,53");
  assert.equal(core.outputs.should_build, "true");
  assert.equal(
    core.outputs.release_notes,
    [
      "- #51: Add CI https://github.com/nova/github-actions/pull/51",
      "- #53: Refactor cache https://github.com/nova/github-actions/pull/53",
    ].join("\n"),
  );
});

test("runAction in diff mode falls back to local rev-parse and handles empty commit range", async () => {
  const core = createCoreMock();
  const { github } = createGithubMock();
  const execSync = createExecSyncMock({
    "git rev-parse refs/remotes/origin/release-2": new Error("not found"),
    "git rev-parse release-2": "local-sha\n",
    "git rev-list origin/main..local-sha --reverse": "",
  });

  await runAction({
    github,
    context,
    core,
    execSync,
    env: {
      INPUT_SRC_REF: "release-2",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.equal(core.outputs.should_build, "false");
  assert.equal(core.outputs.release_notes, "");
  assert.equal(core.outputs.pr_count, "0");
  assert.equal(core.outputs.pr_numbers, "");
  assert.deepEqual(execSync.calls, [
    "git rev-parse refs/remotes/origin/release-2",
    "git rev-parse release-2",
    "git rev-list origin/main..local-sha --reverse",
  ]);
});

test("runAction in diff mode returns empty build when commits exist but none are merged PRs", async () => {
  const core = createCoreMock();
  const { github } = createGithubMock({
    prsByCommit: {
      c1: [
        {
          number: 54,
          title: "Not merged yet",
          html_url: "https://github.com/nova/github-actions/pull/54",
          merged_at: null,
          user: { login: "alice" },
        },
      ],
    },
  });

  const execSync = createExecSyncMock({
    "git rev-parse refs/remotes/origin/release-3": "source-3\n",
    "git rev-list origin/main..source-3 --reverse": "c1\n",
  });

  await runAction({
    github,
    context,
    core,
    execSync,
    env: {
      INPUT_SRC_REF: "release-3",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.equal(core.outputs.should_build, "false");
  assert.equal(core.outputs.release_notes, "");
  assert.equal(core.outputs.pr_count, "0");
  assert.equal(core.outputs.pr_numbers, "");
  assert.match(core.warnings[0], /No merged pull requests found/);
});

test("runAction sets empty output when no merged PRs found in time mode", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-04-01T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github } = createGithubMock({
    paginateResult: [
      {
        number: 61,
        title: "No merge",
        html_url: "https://github.com/nova/github-actions/pull/61",
        merged_at: null,
        user: { login: "ghost" },
      },
    ],
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.equal(core.outputs.should_build, "false");
  assert.equal(core.outputs.release_notes, "");
  assert.equal(core.outputs.pr_count, "0");
  assert.equal(core.outputs.pr_numbers, "");
  assert.match(core.warnings[0], /No merged pull requests found/);
});

test("runAction falls back to plain output when release_notes_format is unknown", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-04-02T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github } = createGithubMock({
    paginateResult: [
      {
        number: 71,
        title: "One",
        html_url: "https://github.com/nova/github-actions/pull/71",
        merged_at: "2026-04-02T11:00:00Z",
        user: { login: "one" },
      },
    ],
    userNamesByHandle: {
      one: "One User",
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "yaml",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.match(core.warnings[0], /Unknown release_notes_format/);
  assert.match(core.outputs.release_notes, /^- #71:/);
  assert.match(
    core.outputs.release_notes,
    /- #71: One https:\/\/github.com\/nova\/github-actions\/pull\/71/,
  );
});

test("runAction caches author lookup and keeps handle when profile lookup fails", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-04-03T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const { github, userCalls } = createGithubMock({
    paginateResult: [
      {
        number: 81,
        title: "A",
        html_url: "https://github.com/nova/github-actions/pull/81",
        merged_at: "2026-04-03T11:00:00Z",
        user: { login: "same-user" },
      },
      {
        number: 82,
        title: "B",
        html_url: "https://github.com/nova/github-actions/pull/82",
        merged_at: "2026-04-03T10:00:00Z",
        user: { login: "same-user" },
      },
      {
        number: 83,
        title: "C",
        html_url: "https://github.com/nova/github-actions/pull/83",
        merged_at: "2026-04-03T09:00:00Z",
        user: { login: "failed-user" },
      },
    ],
    userNamesByHandle: {
      "same-user": "Same User",
    },
    failingUsers: new Set(["failed-user"]),
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain-ext-v1",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.deepEqual(userCalls, ["same-user", "failed-user"]);
  assert.match(core.outputs.release_notes, /same-user\(Same User\)/);
  assert.match(core.outputs.release_notes, /failed-user\(\)/);
});

test("DEFAULT_RETRY_COUNT and DEFAULT_RETRY_DELAY match action.yml defaults", () => {
  const actionYml = require("node:fs").readFileSync(
    require("node:path").join(__dirname, "..", "action.yml"),
    "utf8",
  );

  const retryCountMatch = actionYml.match(
    /retry_count:[\s\S]*?default:\s*"(\d+)"/,
  );
  const retryDelayMatch = actionYml.match(
    /retry_delay:[\s\S]*?default:\s*"(\d+(?:\.\d+)?)"/,
  );

  assert.ok(retryCountMatch, "retry_count default should be present");
  assert.ok(retryDelayMatch, "retry_delay default should be present");
  assert.equal(Number(retryCountMatch[1]), DEFAULT_RETRY_COUNT);
  assert.equal(Number(retryDelayMatch[1]), DEFAULT_RETRY_DELAY);
});

test("parseRetryCount accepts valid non-negative integers", () => {
  const core = createCoreMock();
  assert.equal(parseRetryCount("0", core), 0);
  assert.equal(parseRetryCount("3", core), 3);
  assert.equal(parseRetryCount("  12 ", core), 12);
  assert.equal(core.warnings.length, 0);
});

test("parseRetryCount falls back on empty, missing, or invalid input", () => {
  const core = createCoreMock();
  assert.equal(parseRetryCount(undefined, core), DEFAULT_RETRY_COUNT);
  assert.equal(parseRetryCount(null, core), DEFAULT_RETRY_COUNT);
  assert.equal(parseRetryCount("", core), DEFAULT_RETRY_COUNT);
  assert.equal(parseRetryCount("   ", core), DEFAULT_RETRY_COUNT);
  assert.equal(core.warnings.length, 0);

  assert.equal(parseRetryCount("abc", core), DEFAULT_RETRY_COUNT);
  assert.equal(parseRetryCount("-2", core), DEFAULT_RETRY_COUNT);
  assert.equal(parseRetryCount("1.5", core), DEFAULT_RETRY_COUNT);
  assert.equal(core.warnings.length, 3);
  for (const warning of core.warnings) {
    assert.match(warning, /Invalid retry_count/);
  }
});

test("parseRetryDelay accepts non-negative floats", () => {
  const core = createCoreMock();
  assert.equal(parseRetryDelay("0", core), 0);
  assert.equal(parseRetryDelay("1.5", core), 1.5);
  assert.equal(parseRetryDelay("  30  ", core), 30);
  assert.equal(core.warnings.length, 0);
});

test("parseRetryDelay falls back on empty, missing, or invalid input", () => {
  const core = createCoreMock();
  assert.equal(parseRetryDelay(undefined, core), DEFAULT_RETRY_DELAY);
  assert.equal(parseRetryDelay(null, core), DEFAULT_RETRY_DELAY);
  assert.equal(parseRetryDelay("", core), DEFAULT_RETRY_DELAY);
  assert.equal(parseRetryDelay("   ", core), DEFAULT_RETRY_DELAY);
  assert.equal(core.warnings.length, 0);

  assert.equal(parseRetryDelay("abc", core), DEFAULT_RETRY_DELAY);
  assert.equal(parseRetryDelay("-1", core), DEFAULT_RETRY_DELAY);
  assert.equal(parseRetryDelay("NaN", core), DEFAULT_RETRY_DELAY);
  assert.equal(core.warnings.length, 3);
  for (const warning of core.warnings) {
    assert.match(warning, /Invalid retry_delay/);
  }
});

test("isRetriableError flags 5xx and 429, ignores 4xx and unknown errors", () => {
  assert.equal(isRetriableError(createHttpError(500)), true);
  assert.equal(isRetriableError(createHttpError(502)), true);
  assert.equal(isRetriableError(createHttpError(503)), true);
  assert.equal(isRetriableError(createHttpError(504)), true);
  assert.equal(isRetriableError(createHttpError(599)), true);
  assert.equal(isRetriableError(createHttpError(429)), true);

  assert.equal(isRetriableError(createHttpError(400)), false);
  assert.equal(isRetriableError(createHttpError(401)), false);
  assert.equal(isRetriableError(createHttpError(403)), false);
  assert.equal(isRetriableError(createHttpError(404)), false);
  assert.equal(isRetriableError(createHttpError(422)), false);
  assert.equal(isRetriableError(createHttpError(200)), false);

  assert.equal(isRetriableError(new Error("boom")), false);
  assert.equal(isRetriableError(null), false);
  assert.equal(isRetriableError(undefined), false);
  const weird = new Error("nope");
  weird.status = "503";
  assert.equal(isRetriableError(weird), false);
});

test("withRetry returns immediately on success without sleeping", async () => {
  const sleep = createTrackingSleep();
  const core = createCoreMock();
  let calls = 0;
  const result = await withRetry(
    async () => {
      calls += 1;
      return "ok";
    },
    {
      retryCount: 3,
      retryDelay: 5,
      sleep,
      core,
      label: "test",
    },
  );

  assert.equal(result, "ok");
  assert.equal(calls, 1);
  assert.deepEqual(sleep.calls, []);
  assert.equal(core.warnings.length, 0);
});

test("withRetry retries on 5xx and succeeds when transient errors clear", async () => {
  const sleep = createTrackingSleep();
  const core = createCoreMock();
  const errors = [
    createHttpError(503, "first"),
    createHttpError(502, "second"),
  ];
  let calls = 0;
  const result = await withRetry(
    async () => {
      calls += 1;
      if (errors.length > 0) {
        throw errors.shift();
      }
      return { data: 42 };
    },
    {
      retryCount: 6,
      retryDelay: 10,
      sleep,
      core,
      label: "pulls.list",
    },
  );

  assert.deepEqual(result, { data: 42 });
  assert.equal(calls, 3);
  assert.deepEqual(sleep.calls, [10_000, 10_000]);
  assert.equal(core.warnings.length, 2);
  assert.match(core.warnings[0], /pulls\.list.*HTTP 503.*attempt 1\/6/);
  assert.match(core.warnings[1], /pulls\.list.*HTTP 502.*attempt 2\/6/);
});

test("withRetry retries on 429 status", async () => {
  const sleep = createTrackingSleep();
  const core = createCoreMock();
  let calls = 0;
  const result = await withRetry(
    async () => {
      calls += 1;
      if (calls === 1) {
        throw createHttpError(429, "rate limited");
      }
      return "done";
    },
    {
      retryCount: 2,
      retryDelay: 1,
      sleep,
      core,
      label: "api",
    },
  );

  assert.equal(result, "done");
  assert.equal(calls, 2);
  assert.deepEqual(sleep.calls, [1000]);
});

test("withRetry does not retry on 4xx errors", async () => {
  const sleep = createTrackingSleep();
  const core = createCoreMock();
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw createHttpError(404, "not found");
        },
        {
          retryCount: 6,
          retryDelay: 10,
          sleep,
          core,
          label: "user",
        },
      ),
    /not found/,
  );

  assert.equal(calls, 1);
  assert.deepEqual(sleep.calls, []);
  assert.equal(core.warnings.length, 0);
});

test("withRetry does not retry errors without numeric status", async () => {
  const sleep = createTrackingSleep();
  const core = createCoreMock();
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw new Error("network meltdown");
        },
        {
          retryCount: 6,
          retryDelay: 10,
          sleep,
          core,
          label: "x",
        },
      ),
    /network meltdown/,
  );

  assert.equal(calls, 1);
  assert.deepEqual(sleep.calls, []);
});

test("withRetry exhausts retries and throws the last error", async () => {
  const sleep = createTrackingSleep();
  const core = createCoreMock();
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw createHttpError(500, `attempt ${calls}`);
        },
        {
          retryCount: 3,
          retryDelay: 7,
          sleep,
          core,
          label: "exhaust",
        },
      ),
    /attempt 4/,
  );

  assert.equal(calls, 4);
  assert.deepEqual(sleep.calls, [7000, 7000, 7000]);
  assert.equal(core.warnings.length, 3);
});

test("withRetry with retryCount=0 throws immediately on retriable error", async () => {
  const sleep = createTrackingSleep();
  const core = createCoreMock();
  let calls = 0;
  await assert.rejects(
    () =>
      withRetry(
        async () => {
          calls += 1;
          throw createHttpError(503, "no retries");
        },
        {
          retryCount: 0,
          retryDelay: 10,
          sleep,
          core,
          label: "zero",
        },
      ),
    /no retries/,
  );

  assert.equal(calls, 1);
  assert.deepEqual(sleep.calls, []);
  assert.equal(core.warnings.length, 0);
});

test("runAction in time mode retries paginate on 5xx and succeeds", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-01T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, paginateCalls } = createGithubMock({
    paginateFailures: [
      createHttpError(503, "Service Unavailable"),
      createHttpError(502, "Bad Gateway"),
    ],
    paginateResult: [
      {
        number: 901,
        title: "Resilient PR",
        html_url: "https://github.com/nova/github-actions/pull/901",
        merged_at: "2026-07-01T11:00:00Z",
        user: { login: "alice" },
      },
    ],
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    sleep,
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "Europe/Berlin",
    },
  });

  assert.equal(paginateCalls.length, 3);
  assert.deepEqual(sleep.calls, [10_000, 10_000]);
  assert.equal(core.outputs.should_build, "true");
  assert.equal(core.outputs.pr_numbers, "901");
  assert.equal(core.warnings.length, 2);
  assert.match(core.warnings[0], /pulls\.list.*HTTP 503/);
  assert.match(core.warnings[1], /pulls\.list.*HTTP 502/);
});

test("runAction in time mode propagates paginate error after exhausting retries", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-02T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const failures = [
    createHttpError(503, "fail-1"),
    createHttpError(503, "fail-2"),
    createHttpError(503, "fail-3"),
  ];
  const { github, paginateCalls } = createGithubMock({
    paginateFailures: failures,
  });

  await assert.rejects(
    () =>
      runAction({
        github,
        context,
        core,
        execSync: () => {
          throw new Error("execSync should not be used in time mode");
        },
        sleep,
        env: {
          INPUT_SRC_REF: "",
          INPUT_DST_REF: "main",
          INPUT_HOURS: "24",
          INPUT_RELEASE_NOTES_FORMAT: "plain",
          INPUT_TIMEZONE: "Europe/Berlin",
          INPUT_RETRY_COUNT: "2",
          INPUT_RETRY_DELAY: "3",
        },
      }),
    /fail-3/,
  );

  assert.equal(paginateCalls.length, 3);
  assert.deepEqual(sleep.calls, [3000, 3000]);
  assert.equal(core.warnings.length, 2);
});

test("runAction in time mode does not retry on 4xx and surfaces the error", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-03T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, paginateCalls } = createGithubMock({
    paginateFailures: [createHttpError(404, "branch not found")],
  });

  await assert.rejects(
    () =>
      runAction({
        github,
        context,
        core,
        execSync: () => {
          throw new Error("execSync should not be used in time mode");
        },
        sleep,
        env: {
          INPUT_SRC_REF: "",
          INPUT_DST_REF: "main",
          INPUT_HOURS: "24",
          INPUT_RELEASE_NOTES_FORMAT: "plain",
          INPUT_TIMEZONE: "Europe/Berlin",
        },
      }),
    /branch not found/,
  );

  assert.equal(paginateCalls.length, 1);
  assert.deepEqual(sleep.calls, []);
});

test("runAction in diff mode retries listPullRequestsAssociatedWithCommit on 5xx", async () => {
  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, commitCalls } = createGithubMock({
    prsByCommit: {
      c1: [
        {
          number: 701,
          title: "Recovered PR",
          html_url: "https://github.com/nova/github-actions/pull/701",
          merged_at: "2026-08-01T10:00:00Z",
          user: { login: "alice" },
        },
      ],
    },
    commitFailures: {
      c1: [
        createHttpError(502, "Bad Gateway"),
        createHttpError(504, "Gateway Timeout"),
      ],
    },
  });

  const execSync = createExecSyncMock({
    "git rev-parse refs/remotes/origin/release-7": "source-7\n",
    "git rev-list origin/main..source-7 --reverse": "c1\n",
  });

  await runAction({
    github,
    context,
    core,
    execSync,
    sleep,
    env: {
      INPUT_SRC_REF: "release-7",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "UTC",
      INPUT_RETRY_COUNT: "5",
      INPUT_RETRY_DELAY: "2",
    },
  });

  assert.deepEqual(commitCalls, ["c1", "c1", "c1"]);
  assert.deepEqual(sleep.calls, [2000, 2000]);
  assert.equal(core.outputs.pr_numbers, "701");
  assert.equal(core.outputs.should_build, "true");
  assert.equal(core.warnings.length, 2);
  assert.match(
    core.warnings[0],
    /listPullRequestsAssociatedWithCommit.*HTTP 502/,
  );
});

test("runAction retries getByUsername on 5xx and resolves the author name", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-10T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, userCalls } = createGithubMock({
    paginateResult: [
      {
        number: 401,
        title: "Persistent PR",
        html_url: "https://github.com/nova/github-actions/pull/401",
        merged_at: "2026-07-10T11:00:00Z",
        user: { login: "alice" },
      },
    ],
    userNamesByHandle: {
      alice: "Alice Doe",
    },
    userHttpFailures: {
      alice: [createHttpError(500, "boom")],
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    sleep,
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain-ext-v1",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.deepEqual(userCalls, ["alice", "alice"]);
  assert.deepEqual(sleep.calls, [10_000]);
  assert.match(core.outputs.release_notes, /alice\(Alice Doe\)/);
});

test("runAction getByUsername 4xx is not retried and falls back to empty name", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-11T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, userCalls } = createGithubMock({
    paginateResult: [
      {
        number: 411,
        title: "Ghost PR",
        html_url: "https://github.com/nova/github-actions/pull/411",
        merged_at: "2026-07-11T11:00:00Z",
        user: { login: "ghost" },
      },
    ],
    userHttpFailures: {
      ghost: [createHttpError(404, "not found")],
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    sleep,
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain-ext-v1",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.deepEqual(userCalls, ["ghost"]);
  assert.deepEqual(sleep.calls, []);
  assert.match(core.outputs.release_notes, /ghost\(\)/);
});

test("runAction getByUsername gives up after exhausting retries and falls back to empty name", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-12T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, userCalls } = createGithubMock({
    paginateResult: [
      {
        number: 421,
        title: "Always failing user",
        html_url: "https://github.com/nova/github-actions/pull/421",
        merged_at: "2026-07-12T11:00:00Z",
        user: { login: "broken" },
      },
    ],
    userHttpFailures: {
      broken: [
        createHttpError(503, "1"),
        createHttpError(503, "2"),
        createHttpError(503, "3"),
      ],
    },
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    sleep,
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain-ext-v1",
      INPUT_TIMEZONE: "UTC",
      INPUT_RETRY_COUNT: "2",
      INPUT_RETRY_DELAY: "4",
    },
  });

  assert.deepEqual(userCalls, ["broken", "broken", "broken"]);
  assert.deepEqual(sleep.calls, [4000, 4000]);
  assert.match(core.outputs.release_notes, /broken\(\)/);
});

test("runAction warns on invalid retry inputs and applies defaults", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-15T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, paginateCalls } = createGithubMock({
    paginateFailures: [createHttpError(503, "transient")],
    paginateResult: [],
  });

  await runAction({
    github,
    context,
    core,
    execSync: () => {
      throw new Error("execSync should not be used in time mode");
    },
    sleep,
    env: {
      INPUT_SRC_REF: "",
      INPUT_DST_REF: "main",
      INPUT_HOURS: "24",
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "Europe/Berlin",
      INPUT_RETRY_COUNT: "abc",
      INPUT_RETRY_DELAY: "xyz",
    },
  });

  assert.ok(core.warnings.some((w) => /Invalid retry_count/.test(w)));
  assert.ok(core.warnings.some((w) => /Invalid retry_delay/.test(w)));
  assert.equal(paginateCalls.length, 2);
  assert.deepEqual(sleep.calls, [DEFAULT_RETRY_DELAY * 1000]);
});

test("runAction with retry_count=0 stops retrying paginate after the first failure", async (t) => {
  const realNow = Date.now;
  Date.now = () => Date.parse("2026-07-16T12:00:00Z");
  t.after(() => {
    Date.now = realNow;
  });

  const core = createCoreMock();
  const sleep = createTrackingSleep();
  const { github, paginateCalls } = createGithubMock({
    paginateFailures: [createHttpError(503, "no retries please")],
  });

  await assert.rejects(
    () =>
      runAction({
        github,
        context,
        core,
        execSync: () => {
          throw new Error("execSync should not be used in time mode");
        },
        sleep,
        env: {
          INPUT_SRC_REF: "",
          INPUT_DST_REF: "main",
          INPUT_HOURS: "24",
          INPUT_RELEASE_NOTES_FORMAT: "plain",
          INPUT_TIMEZONE: "Europe/Berlin",
          INPUT_RETRY_COUNT: "0",
        },
      }),
    /no retries please/,
  );

  assert.equal(paginateCalls.length, 1);
  assert.deepEqual(sleep.calls, []);
});

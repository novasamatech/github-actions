"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  DEFAULT_HOURS,
  DEFAULT_TIMEZONE,
  buildCsvReleaseNotes,
  buildPlainReleaseNotes,
  csvEscape,
  formatMergeDate,
  parseHours,
  resolveReleaseNotesFormat,
  resolveTimezone,
  runAction,
} = require("./run");

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
} = {}) {
  const userCalls = [];
  const commitCalls = [];
  const paginateCalls = [];

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
          return { data: prsByCommit[commit_sha] || [] };
        },
      },
    },
    async paginate(fn, params) {
      paginateCalls.push({ fn, params });
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
  const rows = [
    {
      title: "Fix parser",
      link: "https://example.com/pr/1",
      author: "alice(Alice)",
      mergeDate: "2026-01-01",
    },
  ];

  assert.equal(
    buildPlainReleaseNotes(rows),
    "Merged pull requests:\nFix parser ; https://example.com/pr/1 ; alice(Alice) ; 2026-01-01",
  );

  assert.equal(
    buildCsvReleaseNotes(rows),
    "PR Title,PR Link,Author,Merge Date\nFix parser,https://example.com/pr/1,alice(Alice),2026-01-01",
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

  assert.deepEqual(userCalls, ["alice", "bob"]);
  assert.equal(core.outputs.should_build, "true");
  assert.equal(core.outputs.pr_count, "2");
  assert.equal(core.outputs.pr_numbers, "11,14");
  assert.equal(
    core.outputs.release_notes,
    [
      "Merged pull requests:",
      "Fix login ; https://github.com/nova/github-actions/pull/11 ; alice(Alice Doe) ; 2026-02-18",
      "Fast path ; https://github.com/nova/github-actions/pull/14 ; bob() ; 2026-02-18",
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

test("runAction uses default timezone on invalid timezone input", async (t) => {
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
      INPUT_RELEASE_NOTES_FORMAT: "plain",
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
  const { github, commitCalls } = createGithubMock({
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
  assert.equal(core.outputs.pr_count, "2");
  assert.equal(core.outputs.pr_numbers, "51,53");
  assert.equal(core.outputs.should_build, "true");
  assert.equal(
    core.outputs.release_notes,
    [
      "Merged pull requests:",
      "Add CI ; https://github.com/nova/github-actions/pull/51 ; alice(Alice) ; 2026-02-01",
      "Refactor cache ; https://github.com/nova/github-actions/pull/53 ; carol(Carol) ; 2026-02-01",
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
  assert.match(core.outputs.release_notes, /^Merged pull requests:/);
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
      INPUT_RELEASE_NOTES_FORMAT: "plain",
      INPUT_TIMEZONE: "UTC",
    },
  });

  assert.deepEqual(userCalls, ["same-user", "failed-user"]);
  assert.match(core.outputs.release_notes, /same-user\(Same User\)/);
  assert.match(core.outputs.release_notes, /failed-user\(\)/);
});

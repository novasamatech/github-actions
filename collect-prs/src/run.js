"use strict";

const DEFAULT_HOURS = 24;
const FORMAT_PLAIN = "plain";
const FORMAT_PLAIN_EXT_V1 = "plain-ext-v1";
const FORMAT_CSV = "csv";
const FORMAT_MARKDOWN = "markdown";
const DEFAULT_FORMAT = FORMAT_PLAIN;
const DEFAULT_TIMEZONE = "Europe/Berlin";
const SUPPORTED_FORMATS = new Set([
  FORMAT_PLAIN,
  FORMAT_PLAIN_EXT_V1,
  FORMAT_CSV,
  FORMAT_MARKDOWN,
]);

function parseHours(input) {
  const parsed = Number.parseInt(input, 10);
  if (Number.isFinite(parsed) && parsed > 0) {
    return parsed;
  }
  return DEFAULT_HOURS;
}

function resolveReleaseNotesFormat(input, core) {
  const normalized = String(input || DEFAULT_FORMAT)
    .trim()
    .toLowerCase();
  if (SUPPORTED_FORMATS.has(normalized)) {
    return normalized;
  }

  if (core?.warning) {
    core.warning(
      `Unknown release_notes_format '${input}', falling back to '${DEFAULT_FORMAT}'`,
    );
  }
  return DEFAULT_FORMAT;
}

function resolveTimezone(input, core) {
  const timezoneInput = input || DEFAULT_TIMEZONE;
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: timezoneInput }).format(
      new Date(),
    );
    return timezoneInput;
  } catch {
    if (core?.warning) {
      core.warning(
        `Invalid timezone '${timezoneInput}', falling back to '${DEFAULT_TIMEZONE}'`,
      );
    }
    return DEFAULT_TIMEZONE;
  }
}

function csvEscape(value) {
  const stringValue = String(value ?? "");
  if (/[",\n\r]/.test(stringValue)) {
    return `"${stringValue.replace(/"/g, '""')}"`;
  }
  return stringValue;
}

function formatMergeDate(mergedAt, timezone) {
  if (!mergedAt) {
    return "";
  }

  const date = new Date(mergedAt);
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(date);

  const byType = Object.fromEntries(
    parts
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );

  return `${byType.year}-${byType.month}-${byType.day}`;
}

function buildPlainReleaseNotes(merged) {
  const lines = ["Merged pull requests:"];
  for (const pr of merged) {
    const number = pr.number ?? "";
    const title = pr.title || "";
    const link = pr.html_url || "";
    lines.push(`- #${number}: ${title} ${link}`.trimEnd());
  }
  return lines.join("\n");
}

function buildMarkdownReleaseNotes(merged) {
  const lines = ["Merged pull requests:"];
  for (const pr of merged) {
    const number = pr.number ?? "";
    const title = pr.title || "";
    const link = pr.html_url || "";
    lines.push(`- [#${number}](${link}): ${title}`.trimEnd());
  }
  return lines.join("\n");
}

function buildPlainExtV1ReleaseNotes(rows) {
  const lines = ["Merged pull requests:"];
  for (const row of rows) {
    lines.push(`${row.title} ; ${row.link} ; ${row.author} ; ${row.mergeDate}`);
  }
  return lines.join("\n");
}

function buildCsvReleaseNotes(rows) {
  const lines = [
    ["PR Title", "PR Link", "Author", "Merge Date"].map(csvEscape).join(","),
  ];

  for (const row of rows) {
    lines.push(
      [row.title, row.link, row.author, row.mergeDate].map(csvEscape).join(","),
    );
  }

  return lines.join("\n");
}

function setEmptyOutputs(core) {
  core.setOutput("should_build", "false");
  core.setOutput("release_notes", "");
  core.setOutput("pr_count", "0");
  core.setOutput("pr_numbers", "");
}

async function collectRows(merged, getAuthorDisplay, timezone) {
  const rows = [];
  for (const pr of merged) {
    rows.push({
      title: pr.title || "",
      link: pr.html_url || "",
      author: await getAuthorDisplay(pr),
      mergeDate: formatMergeDate(pr.merged_at, timezone),
    });
  }
  return rows;
}

async function runAction({
  github,
  context,
  core,
  execSync,
  env = process.env,
}) {
  const { owner, repo } = context.repo;
  const srcRef = String(env.INPUT_SRC_REF || "").trim();
  const dstRef = String(env.INPUT_DST_REF || "").trim();
  const hours = parseHours(env.INPUT_HOURS);
  const releaseNotesFormat = resolveReleaseNotesFormat(
    env.INPUT_RELEASE_NOTES_FORMAT,
    core,
  );
  const timezone =
    releaseNotesFormat === FORMAT_PLAIN
      ? DEFAULT_TIMEZONE
      : resolveTimezone(env.INPUT_TIMEZONE, core);

  const authorNameCache = new Map();

  const getAuthorDisplay = async (pr) => {
    const handle = pr?.user?.login || "unknown";

    if (!authorNameCache.has(handle)) {
      try {
        const { data: user } = await github.rest.users.getByUsername({
          username: handle,
        });
        authorNameCache.set(handle, user.name || "");
      } catch {
        authorNameCache.set(handle, "");
      }
    }

    const name = authorNameCache.get(handle) || "";
    return `${handle}(${name})`;
  };

  const outputResults = async (merged) => {
    core.setOutput("pr_count", merged.length.toString());
    core.setOutput("pr_numbers", merged.map((pr) => pr.number).join(","));

    if (merged.length === 0) {
      core.warning("No merged pull requests found.");
      core.setOutput("should_build", "false");
      core.setOutput("release_notes", "");
      return;
    }

    let notes;
    if (releaseNotesFormat === FORMAT_PLAIN) {
      notes = buildPlainReleaseNotes(merged);
    } else if (releaseNotesFormat === FORMAT_MARKDOWN) {
      notes = buildMarkdownReleaseNotes(merged);
    } else {
      const rows = await collectRows(merged, getAuthorDisplay, timezone);
      notes =
        releaseNotesFormat === FORMAT_CSV
          ? buildCsvReleaseNotes(rows)
          : buildPlainExtV1ReleaseNotes(rows);
    }

    core.notice(`Found ${merged.length} merged PR(s)`);
    core.info("Release notes:");
    core.info(notes);

    core.setOutput("should_build", "true");
    core.setOutput("release_notes", notes);
  };

  if (srcRef) {
    core.info(
      `Diff mode: collecting PRs from commits between origin/${dstRef} and ${srcRef}`,
    );

    let sourceCommit;
    try {
      sourceCommit = execSync(`git rev-parse refs/remotes/origin/${srcRef}`)
        .toString()
        .trim();
      core.info(`Source ref origin/${srcRef} resolved to: ${sourceCommit}`);
    } catch {
      sourceCommit = execSync(`git rev-parse ${srcRef}`).toString().trim();
      core.info(`Source ref ${srcRef} resolved to commit: ${sourceCommit}`);
    }

    const commitsOutput = execSync(
      `git rev-list origin/${dstRef}..${sourceCommit} --reverse`,
    )
      .toString()
      .trim();

    if (!commitsOutput) {
      core.info(`No commits found between origin/${dstRef} and source ref`);
      setEmptyOutputs(core);
      return;
    }

    const commits = commitsOutput.split("\n").filter(Boolean);
    core.info(`Found ${commits.length} commits to check`);

    const seenPrNumbers = new Set();
    const merged = [];

    for (const commitSha of commits) {
      core.info(`Checking commit: ${commitSha}`);

      const { data: prs } =
        await github.rest.repos.listPullRequestsAssociatedWithCommit({
          owner,
          repo,
          commit_sha: commitSha,
        });

      for (const pr of prs.filter((pr) => pr.merged_at !== null)) {
        if (!seenPrNumbers.has(pr.number)) {
          seenPrNumbers.add(pr.number);
          merged.push(pr);
          core.info(`  Found PR #${pr.number}: ${pr.title}`);
        }
      }
    }

    await outputResults(merged);
    return;
  }

  core.info(
    `Time mode: collecting PRs merged into '${dstRef}' in the last ${hours} hours`,
  );

  const since = new Date(Date.now() - hours * 60 * 60 * 1000);

  const prs = await github.paginate(github.rest.pulls.list, {
    owner,
    repo,
    state: "closed",
    base: dstRef,
    sort: "updated",
    direction: "desc",
    per_page: 100,
  });

  core.info(`Total closed PRs fetched for branch '${dstRef}': ${prs.length}`);

  const merged = prs.filter(
    (pr) => pr.merged_at && new Date(pr.merged_at) >= since,
  );
  core.info(`Merged PRs in last ${hours}h: ${merged.length}`);

  if (merged.length > 0) {
    merged.forEach((pr) => {
      core.info(`  - #${pr.number}: ${pr.title} (merged: ${pr.merged_at})`);
    });
  }

  await outputResults(merged);
}

module.exports = {
  DEFAULT_HOURS,
  DEFAULT_FORMAT,
  DEFAULT_TIMEZONE,
  buildCsvReleaseNotes,
  buildMarkdownReleaseNotes,
  buildPlainReleaseNotes,
  buildPlainExtV1ReleaseNotes,
  csvEscape,
  formatMergeDate,
  parseHours,
  resolveReleaseNotesFormat,
  resolveTimezone,
  runAction,
};

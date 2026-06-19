use crate::AdapterError;
use cerberus_schema::{ChangedFile, FileStatus};
use std::collections::BTreeSet;

pub fn changed_files_from_git_diff(diff: &str) -> Result<Vec<ChangedFile>, AdapterError> {
    if diff.trim().is_empty() {
        return invalid_diff("local diff is empty");
    }

    let mut files = Vec::new();
    let mut current = None;
    for line in diff.lines() {
        if let Some(path) = parse_diff_git_path(line)? {
            finish_file(&mut files, current.take())?;
            current = Some(FileAccumulator::new(path));
            continue;
        }

        let Some(file) = current.as_mut() else {
            if line.trim().is_empty() {
                continue;
            }
            return invalid_diff("local diff must start with a diff --git header");
        };

        if line.starts_with("new file mode ") {
            file.status = FileStatus::Added;
        } else if line.starts_with("deleted file mode ") {
            file.status = FileStatus::Deleted;
        } else if let Some(path) = line.strip_prefix("rename to ") {
            file.path = non_empty_path(path, "rename to")?;
            file.status = FileStatus::Renamed;
        } else if let Some(path) = line.strip_prefix("copy to ") {
            file.path = non_empty_path(path, "copy to")?;
            file.status = FileStatus::Copied;
        } else if line.starts_with('+') && !line.starts_with("+++") {
            file.additions += 1;
        } else if line.starts_with('-') && !line.starts_with("---") {
            file.deletions += 1;
        }
    }
    finish_file(&mut files, current)?;

    if files.is_empty() {
        return invalid_diff("local diff did not contain any changed files");
    }
    let mut seen = BTreeSet::new();
    for file in &files {
        if !seen.insert(file.path.as_str()) {
            return invalid_diff(format!(
                "local diff contains duplicate file path {:?}",
                file.path
            ));
        }
    }
    Ok(files)
}

fn parse_diff_git_path(line: &str) -> Result<Option<String>, AdapterError> {
    let Some(rest) = line.strip_prefix("diff --git ") else {
        return Ok(None);
    };
    let Some(rest) = rest.strip_prefix("a/") else {
        return invalid_diff("diff --git old path must start with a/");
    };
    let Some((old_path, new_path)) = rest.rsplit_once(" b/") else {
        return invalid_diff("diff --git new path must start with b/");
    };
    non_empty_path(old_path, "diff --git old path")?;
    Ok(Some(non_empty_path(new_path, "diff --git")?))
}

fn non_empty_path(path: &str, field: &'static str) -> Result<String, AdapterError> {
    if path.trim().is_empty() {
        invalid_diff(format!("{field} path must not be empty"))
    } else {
        Ok(path.to_string())
    }
}

fn finish_file(
    files: &mut Vec<ChangedFile>,
    file: Option<FileAccumulator>,
) -> Result<(), AdapterError> {
    let Some(file) = file else {
        return Ok(());
    };
    if file.path.trim().is_empty() {
        return invalid_diff("changed file path must not be empty");
    }
    files.push(ChangedFile {
        path: file.path,
        status: file.status,
        additions: file.additions,
        deletions: file.deletions,
    });
    Ok(())
}

fn invalid_diff<T>(reason: impl Into<String>) -> Result<T, AdapterError> {
    Err(invalid_diff_error(reason))
}

fn invalid_diff_error(reason: impl Into<String>) -> AdapterError {
    AdapterError::InvalidGitDiff {
        reason: reason.into(),
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct FileAccumulator {
    path: String,
    status: FileStatus,
    additions: u64,
    deletions: u64,
}

impl FileAccumulator {
    fn new(path: String) -> Self {
        Self {
            path,
            status: FileStatus::Modified,
            additions: 0,
            deletions: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn git_diff_parses_modified_added_deleted_and_renamed_files() {
        let files = changed_files_from_git_diff(
            "diff --git a/src/lib.rs b/src/lib.rs\n--- a/src/lib.rs\n+++ b/src/lib.rs\n@@ -1 +1,2 @@\n-old\n+new\n+line\n\
diff --git a/src/new.rs b/src/new.rs\nnew file mode 100644\n--- /dev/null\n+++ b/src/new.rs\n@@ -0,0 +1 @@\n+new\n\
diff --git a/src/old.rs b/src/old.rs\ndeleted file mode 100644\n--- a/src/old.rs\n+++ /dev/null\n@@ -1 +0,0 @@\n-old\n\
diff --git a/src/before.rs b/src/after.rs\nsimilarity index 100%\nrename from src/before.rs\nrename to src/after.rs\n",
        )
        .expect("diff parses");

        assert_eq!(files.len(), 4);
        assert_eq!(files[0].path, "src/lib.rs");
        assert_eq!(files[0].status, FileStatus::Modified);
        assert_eq!(files[0].additions, 2);
        assert_eq!(files[0].deletions, 1);
        assert_eq!(files[1].status, FileStatus::Added);
        assert_eq!(files[2].status, FileStatus::Deleted);
        assert_eq!(files[3].path, "src/after.rs");
        assert_eq!(files[3].status, FileStatus::Renamed);
    }

    #[test]
    fn git_diff_rejects_malformed_and_duplicate_diffs() {
        assert!(changed_files_from_git_diff("").is_err());
        assert!(changed_files_from_git_diff("+line without header\n").is_err());
        assert!(
            changed_files_from_git_diff("diff --git src/lib.rs b/src/lib.rs\n")
                .expect_err("old path prefix rejects")
                .to_string()
                .contains("old path")
        );
        assert!(changed_files_from_git_diff(
            "diff --git a/src/lib.rs b/src/lib.rs\n+one\n\
diff --git a/src/lib.rs b/src/lib.rs\n+two\n",
        )
        .expect_err("duplicate files reject")
        .to_string()
        .contains("duplicate file path"));
    }

    #[test]
    fn git_diff_accepts_unquoted_paths_with_spaces() {
        let files = changed_files_from_git_diff(
            "diff --git a/docs/space name.md b/docs/space name.md\n--- a/docs/space name.md\t\n+++ b/docs/space name.md\t\n@@ -1 +1 @@\n-old\n+new\n",
        )
        .expect("space path parses");

        assert_eq!(files.len(), 1);
        assert_eq!(files[0].path, "docs/space name.md");
        assert_eq!(files[0].additions, 1);
        assert_eq!(files[0].deletions, 1);
    }
}

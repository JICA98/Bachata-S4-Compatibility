export function uint8ToBase64(bytes: Uint8Array): string {
  let binary = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export async function commitFiles(
  github: (path: string, init?: RequestInit) => Promise<Response>,
  args: {
    owner: string;
    repo: string;
    branch: string;
    baseCommitSha: string;
    baseTreeSha: string;
    message: string;
    files: Array<{path: string; content: Uint8Array}>;
  },
): Promise<string> {
  const blobs = [];
  for (const file of args.files) {
    const response = await github(`/repos/${args.owner}/${args.repo}/git/blobs`, {
      method: "POST",
      body: JSON.stringify({content: uint8ToBase64(file.content), encoding: "base64"}),
    });
    if (!response.ok) throw new Error(`Could not create blob (${response.status})`);
    const data = await response.json() as {sha: string};
    blobs.push({path: file.path, mode: "100644", type: "blob", sha: data.sha});
  }
  const tree = await github(`/repos/${args.owner}/${args.repo}/git/trees`, {
    method: "POST",
    body: JSON.stringify({base_tree: args.baseTreeSha, tree: blobs}),
  });
  if (!tree.ok) throw new Error(`Could not create tree (${tree.status})`);
  const treeSha = ((await tree.json()) as {sha: string}).sha;
  const commit = await github(`/repos/${args.owner}/${args.repo}/git/commits`, {
    method: "POST",
    body: JSON.stringify({message: args.message, tree: treeSha, parents: [args.baseCommitSha]}),
  });
  if (!commit.ok) throw new Error(`Could not create commit (${commit.status})`);
  const commitSha = ((await commit.json()) as {sha: string}).sha;
  const update = await github(`/repos/${args.owner}/${args.repo}/git/refs/heads/${encodeURIComponent(args.branch)}`, {
    method: "PATCH",
    body: JSON.stringify({sha: commitSha}),
  });
  if (!update.ok) throw new Error(`Could not update branch (${update.status})`);
  return commitSha;
}

import {afterEach, describe, expect, it} from "vitest";
import worker from "./index";

const delegated: Request[] = [];

function env() {
  return {
    GITHUB_TOKEN: "token",
    GITHUB_ISSUE_TOKEN: "issue-token",
    GITHUB_OWNER: "JICA98",
    GITHUB_REPO: "Bachata-S4-Compatibility",
    GITHUB_BASE_BRANCH: "feat/community-compatibility-v2",
    ASSETS: {
      async fetch(request: Request) {
        delegated.push(request);
        return new Response("asset response", {status: 200, headers: {"content-type": "application/json"}});
      },
    },
  };
}

afterEach(() => delegated.splice(0));

describe("compatibility feed assets", () => {
  it.each([
    ["GET", "/data/compat/v2/index.json"],
    ["GET", "/data/compat/v2/socs.json"],
    ["GET", "/data/compat/v2/games/CUSA00900.json"],
    ["HEAD", "/data/compat/v2/games/CUSA00900.json"],
  ])("delegates %s %s to ASSETS", async (method, pathname) => {
    const response = await worker.fetch(new Request(`https://example.com${pathname}`, {method}), env() as never);
    expect(response.status).toBe(200);
    if (method === "GET") expect(await response.text()).toBe("asset response");
    expect(delegated).toHaveLength(1);
    expect(delegated[0].method).toBe(method);
    expect(new URL(delegated[0].url).pathname).toBe(pathname);
  });

  it.each([
    "/data/compat/v2/games/CUSA9.json",
    "/data/compat/v2/games/not-a-cusa.json",
    "/data/compat/v2/other.json",
  ])("returns 404 without delegating an invalid feed path: %s", async pathname => {
    const response = await worker.fetch(new Request(`https://example.com${pathname}`), env() as never);
    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({error: "not_found"});
    expect(delegated).toHaveLength(0);
  });
});

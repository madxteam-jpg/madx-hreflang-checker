from urllib.parse import urljoin
import requests
from bs4 import BeautifulSoup


def audit_hreflang_cluster(urls):
    """Audits hreflang declarations across a list of URLs for reciprocity,

    indexability, canonical alignment, and standard status codes.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HreflangAuditor/1.0"
    }

    cluster_data = {}

    print("=== STEP 1: Crawling & Extracting Hreflang Tags ===")
    for url in urls:
        print(f"Fetching: {url}")
        try:
            res = requests.get(url, headers=headers, timeout=10)
            final_url = res.url

            # Basic checks
            is_redirected = final_url != url
            status_code = res.status_code

            soup = BeautifulSoup(res.text, "html.parser")

            # Extract canonical
            canonical_tag = soup.find("link", rel="canonical")
            canonical_url = (
                canonical_tag.get("href") if canonical_tag else None
            )

            # Extract hreflang
            hreflangs = {}
            for link in soup.find_all("link", rel="alternate"):
                lang = link.get("hreflang")
                href = link.get("href")
                if lang and href:
                    hreflangs[lang.lower()] = urljoin(url, href)

            cluster_data[url] = {
                "status_code": status_code,
                "final_url": final_url,
                "is_redirected": is_redirected,
                "canonical": canonical_url,
                "hreflangs": hreflangs,
            }
        except Exception as e:
            print(f"Error fetching {url}: {e}")
            cluster_data[url] = {"error": str(e)}

    print("\n=== STEP 2: Analyzing Reciprocity & Consistency ===")

    # Determine the "master set" (union of all unique (lang, target) pairs discovered)
    master_targets = {}
    for url, data in cluster_data.items():
        if "hreflangs" in data:
            for lang, target in data["hreflangs"].items():
                master_targets[lang] = target

    for url, data in cluster_data.items():
        print(f"\nAudit Report for: {url}")

        if "error" in data:
            print(f"  [CRITICAL] Request Failed: {data['error']}")
            continue

        # Check HTTP & Canonical health
        if data["status_code"] != 200:
            print(f"  [CRITICAL] Non-200 Status Code: {data['status_code']}")

        if data["is_redirected"]:
            print(f"  [WARNING] URL Redirects to: {data['final_url']}")

        if data["canonical"] and data["canonical"] != url:
            print(
                f"  [CRITICAL] Canonicalized to another URL: {data['canonical']}"
            )

        # Check Self-Reference
        declared_urls = set(data["hreflangs"].values())
        if url not in declared_urls:
            print(
                "  [CRITICAL] Missing Self-Reference! Page does not include itself in hreflang tags."
            )

        # Check missing tags compared to full set
        for lang, target in master_targets.items():
            if lang not in data["hreflangs"]:
                print(
                    f"  [INCOMPLETE] Missing entry for locale '{lang}' (Expected: {target})"
                )
            elif data["hreflangs"][lang] != target:
                print(
                    f"  [MISMATCH] Mismatch for locale '{lang}': found '{data['hreflangs'][lang]}', expected '{target}'"
                )

        # Check Reciprocity
        for lang, target in data["hreflangs"].items():
            if target in cluster_data:
                target_hreflangs = cluster_data[target].get("hreflangs", {})
                if url not in target_hreflangs.values():
                    print(
                        f"  [NON-RECIPROCAL] Points to {target} ({lang}), but {target} does NOT link back to {url}"
                    )


# Example usage:
if __name__ == "__main__":
    # Add your market homepage URLs here
    homepage_urls = [
        "https://example.com/en/",
        "https://example.com/ru/",
        "https://example.com/es/",
    ]

    audit_hreflang_cluster(homepage_urls)

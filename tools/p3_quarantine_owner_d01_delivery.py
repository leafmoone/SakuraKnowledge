"""Reuse byte audits for owner-key repair, keeping all prior receipts immutable."""
from pathlib import Path

import p3_quarantine_9d5_delivery as audit


def main():
    audit.SOURCE='8a5b3d23695a43970d1902d6d6dea7c9e7dd1882'
    audit.BASE='d01b23c27eb10f26d2138b8668631bfb0a657ee0'
    audit.PREFIX='review-d01-'
    audit.ART=Path('dist/p3-owner-8a5b3d2')
    audit.main(owner_receipt='owner-release')


if __name__=='__main__':main()

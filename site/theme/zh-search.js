// Chinese-aware search for mdBook.
//
// mdBook builds its elasticlunr index by splitting text on whitespace, so a
// Chinese sentence becomes a single token and queries like "智能指针" never
// match. This replaces the lookup for queries containing CJK with a substring
// scan over the stored document bodies; Latin queries keep using elasticlunr,
// and everything else (result list, teasers, ?highlight= marking) stays as
// mdBook wrote it.
(function () {
    'use strict';

    if (typeof elasticlunr === 'undefined' || !elasticlunr.Index) {
        return;
    }

    var CJK = /[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]/;
    // A query is split into runs of CJK and runs of identifier characters, so
    // "std::vector 迭代器" looks for both parts.
    var TERMS = /[㐀-䶿一-鿿豈-﫿぀-ヿ가-힯]+|[A-Za-z0-9_+#.:<>-]+/g;

    var TITLE_BOOST = 8;
    var CRUMB_BOOST = 3;
    var TEASER_RADIUS = 70;

    function occurrences(haystack, needle) {
        var n = 0;
        var i = haystack.indexOf(needle);
        while (i !== -1) {
            n++;
            i = haystack.indexOf(needle, i + needle.length);
        }
        return n;
    }

    // Cut a window around the first hit. mdBook's teaser builder splits on
    // spaces to decide what to wrap in <em>, so the hit is padded with spaces
    // to make it a "word" it can recognise.
    function teaser(body, terms) {
        var lower = body.toLowerCase();
        var at = -1;
        var hit = '';
        for (var i = 0; i < terms.length; i++) {
            var p = lower.indexOf(terms[i]);
            if (p !== -1 && (at === -1 || p < at)) {
                at = p;
                hit = terms[i];
            }
        }
        if (at === -1) {
            return body.slice(0, TEASER_RADIUS * 2);
        }
        var start = Math.max(0, at - TEASER_RADIUS);
        var end = Math.min(body.length, at + hit.length + TEASER_RADIUS);
        return (start > 0 ? '…' : '')
            + body.slice(start, at)
            + ' ' + body.slice(at, at + hit.length) + ' '
            + body.slice(at + hit.length, end)
            + (end < body.length ? '…' : '');
    }

    var elasticSearch = elasticlunr.Index.prototype.search;

    elasticlunr.Index.prototype.search = function (query, config) {
        if (!query || !CJK.test(query)) {
            return elasticSearch.call(this, query, config);
        }
        try {
            var terms = query.toLowerCase().match(TERMS) || [];
            if (!terms.length) {
                return elasticSearch.call(this, query, config);
            }

            var docs = this.documentStore.docs;
            var results = [];

            Object.keys(docs).forEach(function (ref) {
                var doc = docs[ref];
                var body = (doc.body || '').toLowerCase();
                var title = (doc.title || '').toLowerCase();
                var crumbs = (doc.breadcrumbs || '').toLowerCase();

                var score = 0;
                for (var i = 0; i < terms.length; i++) {
                    var hits = occurrences(body, terms[i])
                        + TITLE_BOOST * occurrences(title, terms[i])
                        + CRUMB_BOOST * occurrences(crumbs, terms[i]);
                    if (hits === 0) {
                        return;   // every term must appear
                    }
                    score += hits;
                }

                results.push({
                    ref: ref,
                    score: score,
                    doc: {
                        id: doc.id,
                        title: doc.title,
                        breadcrumbs: doc.breadcrumbs,
                        body: teaser(doc.body || '', terms),
                    },
                });
            });

            results.sort(function (a, b) {
                return b.score - a.score;
            });
            return results;
        } catch (err) {
            console.error('zh-search fell back to elasticlunr:', err);
            return elasticSearch.call(this, query, config);
        }
    };
})();

'''
    Provides SQL formulas for e.g. the evaluation of
    annotations directly in postgres.

    2019-20 Benjamin Kellenberger
'''

from enum import Enum


class StatisticalFormulas_user(Enum):
    labels = '''
        SELECT q1.image AS image, q2.username, q1id, q2id, q1label, q2label, q1label=q2label AS label_correct
        FROM (
            SELECT image, id AS q1id, label AS q1label
            FROM {id_anno}
            WHERE username = %s
        ) AS q1
        JOIN
        (
            SELECT image, id AS q2id, label AS q2label, username
            FROM {id_anno}
            WHERE username IN %s
        ) AS q2
        ON q1.image = q2.image
        {sql_goldenQuestion}
        ORDER BY image
    '''

    
    points = '''WITH masterQuery AS (
        SELECT q1.image, q2.username, q1.aid AS id1, q2.aid AS id2, q1.label AS label1, q2.label AS label2,
            |/((q1.x - q2.x)^2 + (q1.y - q2.y)^2) AS euclidean_distance
        FROM (
            SELECT iu.image, iu.username, anno.id AS aid, label, x, y, width, height FROM {id_iu} AS iu
            LEFT OUTER JOIN {id_anno} AS anno
            ON iu.image = anno.image AND iu.username = anno.username
            WHERE iu.username = %s
        ) AS q1
        JOIN (
            SELECT iu.image, iu.username, anno.id AS aid, label, x, y, width, height FROM {id_iu} AS iu
            LEFT OUTER JOIN {id_anno} AS anno
            ON iu.image = anno.image AND iu.username = anno.username
            WHERE iu.username IN %s
        ) AS q2
        ON q1.image = q2.image
        {sql_goldenQuestion}
    ),
    imgStats AS (
        SELECT image, username, COUNT(DISTINCT id2) AS num_pred, COUNT(DISTINCT id1) AS num_target
        FROM masterQuery 
        GROUP BY image, username
    ),
    tp AS (
        SELECT username, image,
        (CASE WHEN mindist > %s OR label1 != label2 THEN NULL ELSE bestMatch.id1 END) AS id1,
        aux.id2, mindist AS dist
        FROM (
            SELECT username, id1, MIN(euclidean_distance) AS mindist
            FROM masterQuery
            GROUP BY username, id1
        ) AS bestMatch
        JOIN (
            SELECT image, id1, id2, label1, label2, euclidean_distance
            FROM masterQuery
            WHERE euclidean_distance <= %s
        ) AS aux
        ON bestMatch.id1 = aux.id1
        AND mindist = euclidean_distance
    )
    SELECT *
    FROM (
        SELECT image, username, num_pred, num_target, min_dist, avg_dist, max_dist,
            tp, GREATEST(fp, num_pred - tp) AS fp, GREATEST(fn, num_target - tp) AS fn
        FROM (
            SELECT image, username, num_pred, num_target, min_dist, avg_dist, max_dist,
                LEAST(tp, num_pred) AS tp, fp, fn
            FROM imgStats
            JOIN (
                SELECT username AS username_, image AS image_,
                    MIN(dist) AS min_dist, AVG(dist) AS avg_dist, MAX(dist) AS max_dist,
                    SUM(tp) AS tp, SUM(fp) AS fp, SUM(fn) AS fn
                FROM (
                    SELECT username, image,
                            dist,
                            (CASE WHEN id1 IS NOT NULL AND id2 IS NOT NULL THEN 1 ELSE 0 END) AS tp,
                            (CASE WHEN id2 IS NULL THEN 1 ELSE 0 END) AS fp,
                            (CASE WHEN id1 IS NULL THEN 1 ELSE 0 END) AS fn
                    FROM (
                        SELECT * FROM tp
                        UNION ALL (
                            SELECT username, image, NULL AS id1, id2, NULL AS dist
                            FROM masterQuery
                            WHERE id1 NOT IN (
                                SELECT id1 FROM tp
                            )
                            AND masterQuery.id2 IS NOT NULL
                        )
                        UNION ALL (
                            SELECT username, image, id1, NULL AS id2, NULL AS dist
                            FROM masterQuery
                            WHERE id2 IS NULL
                            AND id1 IS NOT NULL
                        )
                    ) AS q1
                ) AS q2
                GROUP BY image_, username_
            ) AS statsQuery
            ON imgstats.image = statsQuery.image_
            AND imgstats.username = statsQuery.username_
        ) AS q3
    ) AS q4
    UNION ALL (
        SELECT image, username, num_pred, num_target, NULL AS min_dist, NULL AS avg_dist, NULL AS max_dist, 0 AS tp, num_pred AS fp, 0 AS fn
        FROM imgStats
        WHERE num_target = 0
    )'''


    boundingBoxes = '''WITH masterQuery AS (
        SELECT q1.image, q2.username, q1.aid AS id1, q2.aid AS id2, q1.label AS label1, q2.label AS label2,
            intersection_over_union(q1.x, q1.y, q1.width, q1.height,
                                    q2.x, q2.y, q2.width, q2.height) AS iou
        FROM (
            SELECT iu.image, iu.username, anno.id AS aid, label, x, y, width, height FROM {id_iu} AS iu
            LEFT OUTER JOIN {id_anno} AS anno
            ON iu.image = anno.image AND iu.username = anno.username
            WHERE iu.username = %s
        ) AS q1
        JOIN (
            SELECT iu.image, iu.username, anno.id AS aid, label, x, y, width, height FROM {id_iu} AS iu
            LEFT OUTER JOIN {id_anno} AS anno
            ON iu.image = anno.image AND iu.username = anno.username
            WHERE iu.username IN %s
        ) AS q2
        ON q1.image = q2.image
        {sql_goldenQuestion}
    ),
    imgStats AS (
        SELECT image, username, COUNT(DISTINCT id2) AS num_pred, COUNT(DISTINCT id1) AS num_target
        FROM masterQuery 
        GROUP BY image, username
    ),
    tp AS (
        SELECT username, image,
        (CASE WHEN maxiou < %s OR label1 != label2 THEN NULL ELSE bestMatch.id1 END) AS id1,
        aux.id2, maxiou AS iou
        FROM (
            SELECT username, id1, MAX(iou) AS maxiou
            FROM masterQuery
            GROUP BY username, id1
        ) AS bestMatch
        JOIN (
            SELECT image, id1, id2, label1, label2, iou
            FROM masterQuery
            WHERE iou > 0
        ) AS aux
        ON bestMatch.id1 = aux.id1
        AND maxiou = iou
    )
    SELECT *
    FROM (
        SELECT image, username, num_pred, num_target, min_iou, avg_iou, max_iou,
            tp, GREATEST(fp, num_pred - tp) AS fp, GREATEST(fn, num_target - tp) AS fn
        FROM (
            SELECT image, username, num_pred, num_target, min_iou, avg_iou, max_iou,
                LEAST(tp, num_pred) AS tp, fp, fn
            FROM imgStats
            JOIN (
                SELECT username AS username_, image AS image_,
                    MIN(iou) AS min_iou, AVG(iou) AS avg_iou, MAX(iou) AS max_iou,
                    SUM(tp) AS tp, SUM(fp) AS fp, SUM(fn) AS fn
                FROM (
                    SELECT username, image,
                            iou,
                            (CASE WHEN id1 IS NOT NULL AND id2 IS NOT NULL THEN 1 ELSE 0 END) AS tp,
                            (CASE WHEN id2 IS NULL THEN 1 ELSE 0 END) AS fp,
                            (CASE WHEN id1 IS NULL THEN 1 ELSE 0 END) AS fn
                    FROM (
                        SELECT * FROM tp
                        UNION ALL (
                            SELECT username, image, NULL AS id1, id2, NULL::real AS iou
                            FROM masterQuery
                            WHERE id1 NOT IN (
                                SELECT id1 FROM tp
                            )
                            AND masterQuery.id2 IS NOT NULL
                        )
                        UNION ALL (
                            SELECT username, image, id1, NULL AS id2, NULL::real AS iou
                            FROM masterQuery
                            WHERE id2 IS NULL
                            AND id1 IS NOT NULL
                        )
                    ) AS q1
                ) AS q2
                GROUP BY image_, username_
            ) AS statsQuery
            ON imgstats.image = statsQuery.image_
            AND imgstats.username = statsQuery.username_
        ) AS q3
    ) AS q4
    UNION ALL (
        SELECT image, username, num_pred, num_target, NULL AS min_iou, NULL AS avg_iou, NULL AS max_iou, 0 AS tp, num_pred AS fp, 0 AS fn
        FROM imgStats
        WHERE num_target = 0
    )'''


    segmentationMasks = '''
        SELECT q1.image AS image, q1id, q1segMask, q1width, q1height, q2id, q2.username, q2segMask, q2width, q2height FROM (
            SELECT image, id AS q1id, segmentationMask AS q1segMask, width AS q1width, height AS q1height FROM {id_anno}
            WHERE username = %s
        ) AS q1
        JOIN (
            SELECT image, username, id AS q2id, segmentationMask AS q2segMask, width AS q2width, height AS q2height FROM {id_anno}
            WHERE username IN %s
        ) AS q2
        ON q1.image = q2.image
        {sql_goldenQuestion}
    '''



#TODO: rework formulas below
class StatisticalFormulas_model(Enum):
    labels = '''
        SELECT q1.image AS image, cnnstate, q1id, q2id, q1label, q2label, q1label=q2label AS label_correct
        FROM (
            SELECT image, id AS q1id, label AS q1label
            FROM {id_anno}
            WHERE username = %s
        ) AS q1
        JOIN
        (
            SELECT image, id AS q2id, cnnstate, label AS q2label
            FROM {id_pred}
            WHERE cnnstate IN %s
        ) AS q2
        ON q1.image = q2.image
        {sql_goldenQuestion}
        ORDER BY image
    '''

    
    points = '''WITH masterQuery AS (
        SELECT q1.image, q2.cnnstate, q1.aid AS id1, q2.aid AS id2, q1.label AS label1, q2.label AS label2,
            |/((q1.x - q2.x)^2 + (q1.y - q2.y)^2) AS euclidean_distance
        FROM (
            SELECT iu.image, iu.username, anno.id AS aid, label, x, y, width, height FROM {id_iu} AS iu
            LEFT OUTER JOIN {id_anno} AS anno
            ON iu.image = anno.image AND iu.username = anno.username
            WHERE iu.username = 'bkellenb'
        ) AS q1
        JOIN (
            SELECT pred.image, pred.cnnstate, pred.id AS aid, label, x, y, width, height FROM {id_pred} AS pred
            WHERE pred.cnnstate IN %s
        ) AS q2
        ON q1.image = q2.image
    ),
    imgStats AS (
        SELECT image, cnnstate, COUNT(DISTINCT id2) AS num_pred, COUNT(DISTINCT id1) AS num_target
        FROM masterQuery 
        GROUP BY image, cnnstate
    ),
    tp AS (
        SELECT cnnstate, image,
        (CASE WHEN mindist > %s OR label1 != label2 THEN NULL ELSE bestMatch.id1 END) AS id1,
        aux.id2, mindist AS dist
        FROM (
            SELECT cnnstate, id1, MIN(euclidean_distance) AS mindist
            FROM masterQuery
            GROUP BY cnnstate, id1
        ) AS bestMatch
        JOIN (
            SELECT image, id1, id2, label1, label2, euclidean_distance
            FROM masterQuery
            WHERE euclidean_distance <= 0.5
        ) AS aux
        ON bestMatch.id1 = aux.id1
        AND mindist = euclidean_distance
    )
    SELECT *
    FROM (
        SELECT image, cnnstate, num_pred, num_target, min_dist, avg_dist, max_dist,
            tp, GREATEST(fp, num_pred - tp) AS fp, GREATEST(fn, num_target - tp) AS fn
        FROM (
            SELECT image, cnnstate, num_pred, num_target, min_dist, avg_dist, max_dist,
                LEAST(tp, num_pred) AS tp, fp, fn
            FROM imgStats
            JOIN (
                SELECT cnnstate AS cnnstate_, image AS image_,
                    MIN(dist) AS min_dist, AVG(dist) AS avg_dist, MAX(dist) AS max_dist,
                    SUM(tp) AS tp, SUM(fp) AS fp, SUM(fn) AS fn
                FROM (
                    SELECT cnnstate, image,
                            dist,
                            (CASE WHEN id1 IS NOT NULL AND id2 IS NOT NULL THEN 1 ELSE 0 END) AS tp,
                            (CASE WHEN id2 IS NULL THEN 1 ELSE 0 END) AS fp,
                            (CASE WHEN id1 IS NULL THEN 1 ELSE 0 END) AS fn
                    FROM (
                        SELECT * FROM tp
                        UNION ALL (
                            SELECT cnnstate, image, NULL AS id1, id2, NULL AS dist
                            FROM masterQuery
                            WHERE id1 NOT IN (
                                SELECT id1 FROM tp
                            )
                            AND masterQuery.id2 IS NOT NULL
                        )
                        UNION ALL (
                            SELECT cnnstate, image, id1, NULL AS id2, NULL AS dist
                            FROM masterQuery
                            WHERE id2 IS NULL
                            AND id1 IS NOT NULL
                        )
                    ) AS q1
                ) AS q2
                GROUP BY image_, cnnstate_
            ) AS statsQuery
            ON imgstats.image = statsQuery.image_
            AND imgstats.cnnstate = statsQuery.cnnstate_
        ) AS q3
    ) AS q4
    UNION ALL (
        SELECT image, cnnstate, num_pred, num_target, NULL AS min_dist, NULL AS avg_dist, NULL AS max_dist, 0 AS tp, num_pred AS fp, 0 AS fn
        FROM imgStats
        WHERE num_target = 0
    )'''


    boundingBoxes = '''WITH masterQuery AS (
        SELECT q1.image, q2.cnnstate, q1.aid AS id1, q3.aid AS id2, q1.label AS label1, q3.label AS label2,
            intersection_over_union(q1.x, q1.y, q1.width, q1.height,
                                    q3.x, q3.y, q3.width, q3.height) AS iou
        FROM (
            SELECT iu.image, iu.username, anno.id AS aid, label, x, y, width, height FROM {id_iu} AS iu
            LEFT OUTER JOIN {id_anno} AS anno
            ON iu.image = anno.image AND iu.username = anno.username
            WHERE iu.username = %s
        ) AS q1
        LEFT OUTER JOIN (
            SELECT unnest(%s::uuid[]) AS cnnstate
        ) AS q2 ON TRUE
        LEFT OUTER JOIN (
            SELECT image, cnnstate, id AS aid, label, x, y, width, height
            FROM {id_pred}
        ) AS q3
        ON q1.image = q3.image AND q2.cnnstate = q3.cnnstate
        {sql_goldenQuestion}
    ),
    positive AS (
        SELECT bestMatch.image, bestMatch.cnnstate, aux.id1, bestMatch.id2, aux.label1, aux.label2, bestMatch.maxiou AS iou
        FROM (
            SELECT image, cnnstate, id2, MAX(iou) AS maxiou
            FROM masterQuery
            WHERE iou >= %s
            GROUP BY image, cnnstate, id2
        ) AS bestMatch
        JOIN (
            SELECT *
            FROM masterQuery
        ) AS aux
        ON bestMatch.image = aux.image
        AND bestMatch.cnnstate = aux.cnnstate
        AND bestMatch.id2 = aux.id2
        AND maxiou = iou
    ),
    truePositive AS (
        SELECT image, cnnstate, id1, id2
        FROM positive
        WHERE label1 = label2
    ),
    falsePositive AS (
        SELECT image, cnnstate, id1, id2
        FROM positive
        WHERE label1 != label2 AND id2 NOT IN (SELECT id2 FROM truePositive)
        UNION ALL (
            SELECT image, cnnstate, NULL AS id1, id2
            FROM masterQuery
            WHERE id2 NOT IN (SELECT id2 FROM positive)
            GROUP BY image, cnnstate, id2
        )
    )
    SELECT q1.image, q1.cnnstate, num_pred, num_target, min_iou, avg_iou, max_iou,
        (CASE WHEN tp IS NULL THEN 0 ELSE tp END) AS tp,
        (CASE WHEN fp IS NULL THEN 0 ELSE fp END) AS fp,
        (num_target - (CASE WHEN tp IS NULL THEN 0 ELSE tp END)) AS fn
    FROM (
        SELECT image, cnnstate, COUNT(DISTINCT id2) AS num_pred, COUNT(DISTINCT id1) AS num_target
        FROM masterQuery
        GROUP BY image, cnnstate
    ) AS q1
    LEFT OUTER JOIN (
        SELECT sq1.image, sq1.cnnstate, MIN(sq1.iou) AS min_iou, AVG(sq1.iou) AS avg_iou, MAX(sq1.iou) AS max_iou
        FROM (
            SELECT image, cnnstate, id2, iou
            from masterQuery
            WHERE iou > 0
        ) as sq1
        GROUP BY image, cnnstate
    ) AS q2
    ON q1.image = q2.image AND q1.cnnstate = q2.cnnstate
    LEFT OUTER JOIN (
        SELECT image, cnnstate, COUNT(DISTINCT id1) AS tp
        FROM truePositive
        GROUP BY image, cnnstate
    ) AS q3
    ON q1.image = q3.image AND q1.cnnstate = q3.cnnstate
    LEFT OUTER JOIN (
        SELECT image, cnnstate, COUNT(DISTINCT id2) AS fp
        FROM falsePositive
        GROUP BY image, cnnstate
    ) AS q4
    ON q1.image = q4.image AND q1.cnnstate = q4.cnnstate
    '''

    segmentationMasks = '''
        SELECT q1.image AS image, q1id, q1segMask, q1width, q1height, q2id, q2.cnnstate, q2segMask, q2width, q2height FROM (
            SELECT image, id AS q1id, segmentationMask AS q1segMask, width AS q1width, height AS q1height FROM {id_anno}
            WHERE username = %s
        ) AS q1
        JOIN (
            SELECT image, id AS q2id, cnnstate, segmentationMask AS q2segMask, width AS q2width, height AS q2height FROM {id_pred}
            WHERE cnnstate IN %s
        ) AS q2
        ON q1.image = q2.image
        {sql_goldenQuestion}
    '''
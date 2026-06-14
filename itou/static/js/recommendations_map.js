// Renders an OpenLayers map of recommendations for a beneficiary, with a popup
// on each marker showing the recommendation's kind, name, and address.
// Data comes from the `#recommendations-map-points` JSON script tag emitted by
// the `beneficiary_actions.html` template (see `map_points` in the view).
document.addEventListener("DOMContentLoaded", function () {
    const target = document.getElementById("recommendations-map");
    const dataNode = document.getElementById("recommendations-map-points");
    if (!target || !dataNode) {
        return;
    }

    const points = JSON.parse(dataNode.textContent);

    // https://openlayers.org/en/latest/apidoc/module-ol_style_Style-Style.html
    const markerStyle = new ol.style.Style({
        image: new ol.style.Circle({
            radius: 7,
            fill: new ol.style.Fill({ color: "#000091" }),
            stroke: new ol.style.Stroke({ color: "#ffffff", width: 2 }),
        }),
    });

    const features = points.map(function (point) {
        // https://openlayers.org/en/latest/apidoc/module-ol_Feature-Feature.html
        const feature = new ol.Feature({
            geometry: new ol.geom.Point(ol.proj.fromLonLat([point.lon, point.lat])),
            kind_label: point.kind_label,
            name: point.name,
            address: point.address,
        });
        feature.setStyle(markerStyle);
        return feature;
    });

    // https://openlayers.org/en/latest/apidoc/module-ol_layer_Vector-VectorLayer.html
    const vectorLayer = new ol.layer.Vector({
        source: new ol.source.Vector({ features: features }),
    });

    // https://openlayers.org/en/latest/apidoc/module-ol_source_OSM-OSM.html
    const osmSource = new ol.source.OSM({
        // Relax the referrer policy for tile images only so a Referer is sent and
        // OSM tiles load (see also itou/utils/admin.py), avoid 403 errors
        tileLoadFunction: function (tile, src) {
            const img = tile.getImage();
            img.referrerPolicy = "strict-origin-when-cross-origin";
            img.src = src;
        },
    });

    // The overlay element is only a positioning anchor, the visible popup is a
    // manually-triggered Bootstrap tooltip attached to it (see htmx_compat.js for the
    // same manual-construction pattern)
    const popupElement = document.getElementById("recommendations-map-popup");
    // https://openlayers.org/en/latest/apidoc/module-ol_Overlay-Overlay.html
    const popup = new ol.Overlay({
        element: popupElement,
        positioning: "bottom-center",
        stopEvent: true,
    });
    // Bootstrap's Tooltip.show() bails unless `title` resolves to a non-empty value
    // (its content guard only inspects the title, not setContent()), so feed the current
    // marker's HTML through a `title` function that is re-resolved on each show
    let popupContent = "";
    const tooltip = new bootstrap.Tooltip(popupElement, {
        html: true,
        animation: false,
        trigger: "manual", // 'show' and 'hide' are called explicitly in code
        placement: "top",
        title: () => popupContent,
    });

    // https://openlayers.org/en/latest/apidoc/module-ol_Map-Map.html
    const map = new ol.Map({
        target: target,
        layers: [new ol.layer.Tile({ source: osmSource }), vectorLayer],
        overlays: [popup],
        view: new ol.View({
            // Sensible default (Paris) used when no markers are available
            center: ol.proj.fromLonLat([2.333, 48.866]),
            zoom: 12,
        }),
    });

    if (features.length) {
        map.getView().fit(vectorLayer.getSource().getExtent(), {
            padding: [40, 40, 40, 40],
            maxZoom: 15,
        });
    }

    function popupLine(text, className) {
        const line = document.createElement("div");
        line.textContent = text || "";
        if (className) {
            line.className = className;
        }
        return line;
    }

    // Show a marker's details on click, hide the popup when clicking elsewhere
    map.on("singleclick", function (evt) {
        const feature = map.forEachFeatureAtPixel(evt.pixel, (candidate) => candidate);
        if (!feature) {
            tooltip.hide();
            popup.setPosition(undefined);
            return;
        }
        const content = document.createElement("div");
        content.append(
            popupLine(feature.get("kind_label"), "fw-bold"),
            popupLine(feature.get("name")),
            popupLine(feature.get("address"), "text-muted"),
        );
        // `content` is built with textContent, so its serialized HTML is escaped (XSS-safe
        // even though the tooltip renders it as HTML)
        popupContent = content.innerHTML;
        popup.setPosition(feature.getGeometry().getCoordinates());
        // Re-show so the `title` function is re-resolved with the new marker's content
        tooltip.hide();
        tooltip.show();
    });

    // Dismiss the popup as soon as the map moves so it never drifts outside the map area
    map.on("movestart", function () {
        tooltip.hide();
        popup.setPosition(undefined);
    });

    // Set a hand cursor over clickable markers in the map
    map.on("pointermove", function (evt) {
        map.getTargetElement().style.cursor = map.hasFeatureAtPixel(evt.pixel) ? "pointer" : "";
    });
});

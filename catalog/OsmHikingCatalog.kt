package com.example.domain.model

import java.util.Locale

/** Tag semantics shared by classification, Overpass queries and the hiking legend. */
object OsmHikingCatalog {
    data class Selector(val tags: Map<String, String>, val named: Boolean = false) {
        fun matches(values: Map<String, String>): Boolean =
            tags.all { (key, value) -> values[key] == value } &&
                (!named || !values["name"].isNullOrBlank())

        fun overpass(): String = tags.entries.joinToString("") { (k, v) -> "[\"$k\"=\"$v\"]" } +
            if (named) "[\"name\"]" else ""
    }

    data class Entry(val category: PoiCategory, val selectors: List<Selector>, val automaticPoi: Boolean = true)
    private fun s(vararg tags: Pair<String, String>, named: Boolean = false) = Selector(mapOf(*tags), named)
    private fun e(category: PoiCategory, vararg selectors: Selector, automatic: Boolean = true) =
        Entry(category, selectors.toList(), automatic)

    // Specific water types precede generic features. Land-cover features stay map information;
    // bridge/ferrata POIs use actual geometry rather than arbitrary bounding-box centers.
    val entries: List<Entry> = listOf(
        e(PoiCategory.CUMBRE, s("natural" to "peak"), s("natural" to "volcano")),
        e(PoiCategory.MIRADOR, s("tourism" to "viewpoint")),
        e(PoiCategory.REFUGIO, s("tourism" to "alpine_hut"), s("tourism" to "wilderness_hut"), s("amenity" to "shelter")),
        e(PoiCategory.TERMAL, s("natural" to "hot_spring")),
        e(PoiCategory.MANANTIAL, s("natural" to "spring")),
        e(PoiCategory.FUENTE_ORNAMENTAL, s("amenity" to "fountain")),
        e(PoiCategory.FUENTE, s("amenity" to "drinking_water"), s("amenity" to "water_point"),
            s("man_made" to "water_tap", "drinking_water" to "yes")),
        e(PoiCategory.CASCADA, s("waterway" to "waterfall")),
        e(PoiCategory.EMBALSE, s("landuse" to "reservoir"), s("natural" to "water", "water" to "reservoir"), automatic = false),
        e(PoiCategory.RIO, s("waterway" to "river"), s("waterway" to "stream"), s("natural" to "water", "water" to "river"), automatic = false),
        e(PoiCategory.LAGO, s("natural" to "lake"), s("natural" to "water", "water" to "lake"), s("natural" to "water", "water" to "pond"), s("natural" to "water", "water" to "lagoon"), automatic = false),
        e(PoiCategory.CUEVA, s("natural" to "cave_entrance")),
        e(PoiCategory.COLLADO, s("natural" to "saddle"), s("natural" to "pass"), s("mountain_pass" to "yes")),
        e(PoiCategory.BARRANCO, s("natural" to "gorge"), automatic = false),
        e(PoiCategory.BOSQUE, s("natural" to "wood"), s("landuse" to "forest"), automatic = false),
        e(PoiCategory.ARBOL_SINGULAR, s("natural" to "tree", named = true), s("natural" to "tree", "denotation" to "natural_monument")),
        e(PoiCategory.AREA_RECREATIVA, s("tourism" to "picnic_site"), s("tourism" to "camp_site")),
        e(PoiCategory.SENDERO, s("information" to "guidepost")),
        e(PoiCategory.RUINA, s("historic" to "ruins")),
        e(PoiCategory.CASTILLO, s("historic" to "castle"), s("historic" to "fort")),
        e(PoiCategory.ERMITA, s("historic" to "wayside_shrine"), s("building" to "chapel")),
        e(PoiCategory.YACIMIENTO, s("historic" to "archaeological_site")),
        e(PoiCategory.TORRE, s("man_made" to "tower", "tower:type" to "observation"), s("man_made" to "watchtower")),
        e(PoiCategory.FARO, s("man_made" to "lighthouse")),
        e(PoiCategory.VIA_FERRATA, s("route" to "via_ferrata"), s("highway" to "via_ferrata")),
        e(PoiCategory.PUENTE, s("man_made" to "bridge"), s("bridge" to "yes")),
        e(PoiCategory.ESCALADA, s("sport" to "climbing"), automatic = false),
        e(PoiCategory.OTRO, automatic = false)
    )

    val geometryPoiCategories = setOf(PoiCategory.PUENTE, PoiCategory.VIA_FERRATA)

    val geometryPoiSelectors: List<String> get() = entries.filter { it.category in geometryPoiCategories }
        .flatMap { it.selectors }.map { it.overpass() }.distinct()

    val poiSelectors: List<String> get() = entries.filter { it.automaticPoi }
        .flatMap { it.selectors }.map { it.overpass() }.distinct()

    fun classify(tags: Map<String, String>): PoiCategory {
        val normalized = tags.mapKeys { it.key.lowercase(Locale.ROOT) }
            .mapValues { it.value.trim().lowercase(Locale.ROOT) }
        return entries.firstOrNull { entry -> entry.selectors.any { it.matches(normalized) } }
            ?.category ?: PoiCategory.OTRO
    }
}

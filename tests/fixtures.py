"""Small synthetic sheets shaped like the real ones. No real costs or prices."""
import copy

PRICE_HDR = [[], ["", "", "", "", "DOMESTIC"], ["", "", "WHOLESALE PRICE LIST"],
             ["CATEGORY", "SKU", "PRODUCT NAME", "MSRP (USD)", "WHOLESALE (USD)", "DISTRO (USD)"]]


def price_tab(rows, distro=False):
    out = copy.deepcopy(PRICE_HDR)
    for r in rows:
        out.append(r if distro else r[:5])
    return out


def sources():
    base = [["MICRO II"],
            ["", "GPM-001-APZZ", "G Pen Micro II Vaporizer", "$99.95", "$60.00", "$51.00"],
            ["", "GPM-001-APZZ-Inner Pack", "Micro II 10-Pack POP", "$999.50", "$600.00", "$510.00"],
            ["NEW", "GPD-002-AMGD", "Dash Mouthpiece - Red", "$9.95", "$6.00", "$5.10"]]
    stg = [["STÜNDENGLASS"], ["", "SG4-KIT-STGR-02", "Gravity Infuser - Olive Green", "$449.95", "$229.00", "$194.65"]]
    tabs = {}
    for t in ("GP US WS", "GP US D", "GP CA WS", "GP CA D", "GP EU WS", "GP EU D"):
        tabs[t] = price_tab(base, distro=t.endswith(" D"))
    for t in ("STG US WS", "STG US D", "STG CA WS", "STG CA D", "STG EU W", "STG EU D"):
        tabs[t] = price_tab(stg, distro=t.endswith(" D"))
    tabs["GP EU WS"][5][3] = "$99.95"          # $ typo on a EUR tab
    tabs["GP/STG ORDER FORM"] = copy.deepcopy(PRICE_HDR) + [["", "GPM-001-APZZ", "Micro II", "$99.95", "$60.00", "1", "$60"]]
    tabs["GP/STG EX-FACTORY UNIT COSTS"] = copy.deepcopy(PRICE_HDR) + [["", "GPM-001-APZZ", "Micro II", "$99.95", "$60.00", "$10.00"]]

    gp_hdr = ["", "Full Name", "Product Cost (Per Unit)", "Landed Cost", "MSRP", "GNLN SKU", "Units Per Case", "Company CODE",
              "Product Code", "Accesory Name", "Brand & Color Code", "Country Code", "Active", "Product Class", "Company",
              "Producer", "Die Line Designs", "Packaging Design Files", "Barcode", "UPC", "Product Weight (kg)",
              "Product Dimensions (mm)", "Case Weight (kg)", "Case Dimensions (mm)"]
    def gp(code, name, cost="", active="Active", color="ZZ", upc_="811736020343", case="100"):
        r = [""] * len(gp_hdr)
        r[0], r[1], r[2], r[3], r[4], r[6], r[10], r[12] = code, name, cost, "", "$99.95", case, color, active
        r[15], r[18], r[19] = "WEEKE", upc_, f"{name}_00{upc_} UPC-A SST1.eps"
        r[20], r[21] = "0.05", "18 x 18 x 90 mm"
        return r
    master_gp = [gp_hdr,
                 gp("GPM-001-APZZ", "G Pen Micro II Vaporizer", cost="$12.00", active="Inactive"),
                 gp("GPD-002-AMGD", "DASH MOUTHPIECE - RED", color="BLU", upc_="811736027670"),
                 ["----"],
                 gp("GPX-999-ZZZZ", "Old thing", upc_="811736099999")]
    # rows 2..5; add filler so the dropped duplicate sits at row 84 like the real sheet
    while len(master_gp) < 83:
        master_gp.append([])
    master_gp.append(gp("GPD-002-AMGD", "DASH MOUTHPIECE - BLU", color="RED", upc_="811736027670"))  # row 84: dropped
    sg_hdr = ["SG", "Full Name", "Product Cost (Per Unit)", "Landed Cost", "MSRP", "GNLN SKU", "Units Per Case", "MPN",
              "Company CODE", "Product Code", "Accesory Name", "Brand & Color Code", "Country Code", "Active", "Product Class",
              "Company", "Producer", "Die Line Designs", "Packaging Design Files", "Barcode", "UPC"]
    sg_row = ["SG4-KIT-STGR-02", "Stündenglass Gravity Infuser - Green", "$300000000000", "", "$499.95", "", "1", "",
              "ST", "SG4", "KIT", "STGR", "02", "Active", "HOOKAH", "Stündenglass Technologies", "Dongguan Medica Tech",
              "", "", "", "811736029995"]
    master = {"Stundenglass": [sg_hdr, sg_row], "G Pen": master_gp}

    tpl_hdr = ["", "Product", "Retail POP Display SKU", "Full Name", "UPC", "Product Dimensions (L × W × H, incl. unit)",
               "Unit Weight (incl. unit, e.g. 45 g)", "Ships in POP Display? (Yes/No)", "Units per POP Display",
               "Units per Master Case", "Case Weight (incl. unit, e.g. 16.07 kg)", "Case Dimensions (L × W × H, incl. unit)",
               "HTS (Harmonized Tariff Schedule) Code"]
    gp_tpl = {"SKU Details": [[], ["", "G Pen"], ["", "notes"], tpl_hdr,
                              ["", "Micro II", "GPM-001-APZZ", "MICRO II", "811736020999", "18 x 18 x 90 mm", "45 gr", "Yes", "10", "200", "9.5 Kg", "400 x 300 x 200 mm", "8543.70.9940"]]}
    sg_tpl_hdr = ["", "Product", "Full Product Name", "SKU", "UPC", "Product Dimensions (L × W × H, incl. unit)",
                  "Unit Weight (incl. unit, e.g. 2.5 kg)", "Units per Case", "Case Weight (incl. unit, e.g. 16 kg)",
                  "Case Dimensions (L × W × H, incl. unit)", "Units per Pallet", "Pallet Weight (incl. unit, e.g. 320 kg)",
                  "HTS (Harmonized Tariff Schedule) Code"]
    sg_tpl = {"SKU Details": [[], ["", "STG"], ["", "notes"], sg_tpl_hdr]}

    cin_hdr = ["Category", "SKU", "ProductName", "Location", "Bin", "BatchSerialNumber", "ExpiryDate", "Discount", "StockValue",
               "OnHand", "VolumeOnHand", "Available", "OnOrder", "InTransit", "Allocated", "Status", "Unit", "Family",
               "StockLocator", "Brand", "PriceTier1", "PriceTier2", "PriceTier3"]
    def cin(code, loc, avail, status="ACTIVE", t1="", t2="", t3=""):
        r = [""] * len(cin_hdr)
        r[0], r[1], r[2], r[3], r[9], r[11], r[15], r[19] = "Cat", code, code + " name", loc, str(avail), str(avail), status, "Grenco Science"
        r[20], r[21], r[22] = t1, t2, t3
        return r
    cin7 = {"AvailabilityReport_2026-10-22": [cin_hdr,
            cin("GPM-001-APZZ", "Anlerr", 0, t1="99.95", t2="60", t3="49"),
            cin("GPX-999-ZZZZ", "Anlerr", 5),                         # Tier 2
            cin("GPX-888-ZZZZ", "Tradeshow", 7),                      # stock only in an excluded location -> Tier 3
            cin("GPX-777-ZZZZ", "WeFill GPEN B2C", 0, "DEPRECATED"),  # Tier 3
            cin("GHK-001-AOZZ-20", "Anlerr", 50),                     # excluded pack
            cin("GHO-007-AOZZ-10", "Anlerr", 3),                      # kept pack
            cin("GG00-ASH-FL-10", "Anlerr", 9),                       # Grenco Goods, excluded
            cin("ROUTEINS10", "Anlerr", 0)]}
    mk = lambda key, name, tabs: {"key": key, "id": key + "-id", "name": name, "read_at": "2026-10-22", "tabs": tabs}
    return {"prices": mk("prices", "Price Lists", tabs), "master": mk("master", "Master SKU-List GS Holistic", master),
            "cin7": mk("cin7", "Cin7 INVENTORY", cin7), "gp_tpl": mk("gp_tpl", "G-Pen-SKU-Details-Template", gp_tpl),
            "sg_tpl": mk("sg_tpl", "Stundenglass-SKU-Details-Template", sg_tpl)}

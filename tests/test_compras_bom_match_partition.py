from modules.compras.service import _separar_matches_bom


def test_separar_matches_bom_deja_baja_como_sugerencia():
    match_result = {
        0: {'id_item': 'ITEM-ALTA', 'confianza': 'ALTA', 'origen': 'CLAVE_SAT'},
        1: {'id_item': 'ITEM-BAJA', 'confianza': 'BAJA', 'origen': 'TEXTO'},
        2: None,
    }

    bom_item_map, match_meta_map, suggestion_map = _separar_matches_bom(match_result)

    assert bom_item_map == {0: 'ITEM-ALTA'}
    assert match_meta_map == {0: {'confianza': 'ALTA', 'origen': 'CLAVE_SAT'}}
    assert suggestion_map == {
        1: {'id_item': 'ITEM-BAJA', 'confianza': 'BAJA', 'origen': 'TEXTO'}
    }

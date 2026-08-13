(function () {
  "use strict";
  function address(place) {
    const result = {street: "", city: "", state: "", postal: "", country: ""};
    let streetNumber = "", route = "";
    (place.address_components || []).forEach(function (component) {
      const types = component.types || [];
      if (types.includes("street_number")) streetNumber = component.long_name;
      if (types.includes("route")) route = component.long_name;
      if (types.includes("locality") || types.includes("postal_town")) result.city = component.long_name;
      if (!result.city && types.includes("administrative_area_level_2")) result.city = component.long_name;
      if (types.includes("administrative_area_level_1")) result.state = component.short_name;
      if (types.includes("postal_code")) result.postal = component.long_name;
      if (types.includes("country")) result.country = component.long_name;
    });
    result.street = [streetNumber, route].filter(Boolean).join(" ");
    return result;
  }
  async function attach(input, callback) {
    const {Autocomplete} = await google.maps.importLibrary("places");
    const autocomplete = new Autocomplete(input, {
      fields: ["name", "formatted_address", "address_components", "geometry", "website", "types"],
      types: ["establishment", "geocode"]
    });
    autocomplete.addListener("place_changed", function () {
      const place = autocomplete.getPlace();
      if (!place.geometry || !place.geometry.location) return;
      callback({
        name: place.name || input.value,
        formattedAddress: place.formatted_address || "",
        address: address(place), website: place.website || "",
        type: (place.types || [])[0] || "",
        position: {lat: place.geometry.location.lat(), lng: place.geometry.location.lng()}
      });
    });
    return autocomplete;
  }
  window.RadioOutdoorsLocationAutocomplete = {attach: attach};
})();

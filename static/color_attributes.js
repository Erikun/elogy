(function () {
    
    function stringToColour(str) {
        // create a "random" color based on the given string
        var hash = 0;
        for (var i = 0; i < str.length; i++) {
            hash = str.charCodeAt(i) + ((hash << 5) - hash);
        }
        var colour = [];
        for (var i = 0; i < 3; i++) {
            var value = (hash >> (i * 8)) & 0xFF;
            // make the color washed out so that it works as text background
            colour.push(Math.round(2*256/3 + value/3))
        }
        return colour;
    }
    
    [].forEach.call(
        document.querySelectorAll('.attribute'),
        function (el) {
            var color = stringToColour(el.dataset.name);
            console.log("color", color);
            el.style.background = "rgba(" + color.join(",") + ",1)";
        }
    );
    
})();
